import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { isReadonly } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

class ApiError extends Error {
    constructor(message, status, body) {
        super(message);
        this.status = status;
        this.body = body;
    }
}

class DetailedError extends Error {
    constructor(message, status) {
        super(message);
        this.originalResponse = status === 0 ? null : { getStatus: () => status };
    }
}

const api = {
    ApiError,
    requestJson() {
        assert.fail('Uploads must not use requestJson');
    },
};

async function loadTransport(t, tus, auth) {
    return importTypeScript(t, 'src/lib/utils/taskTusUpload.ts', {
        'tus-js-client': tus,
        'src/boot/api': {
            tusEndpoint: 'https://hud.test/tus/files/',
        },
        'src/lib/api': api,
        'src/lib/auth': auth,
    });
}

async function fixture(t, { abortPromise = Promise.resolve() } = {}) {
    const uploads = [];
    let ownerId = 'owner';
    let token = 'first-token';

    const auth = {
        getAuthSubject: () => ownerId,
        getAccessToken: () => token,
    };

    class Upload {
        constructor(file, options) {
            this.file = file;
            this.options = options;
            this.url = options.uploadUrl;
            this.aborts = [];
            uploads.push(this);
        }

        start() {}

        findPreviousUploads() {
            assert.fail('Task uploads must not discover previous uploads');
        }

        abort(terminate) {
            this.aborts.push(terminate);
            return abortPromise;
        }
    }

    const transport = await loadTransport(t, { Upload, DetailedError }, auth);
    const tasks = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const idempotency = await importTypeScript(t, 'src/lib/idempotentRequests.ts', {
        'src/lib/api': api,
    });
    const { VideoUploadTask } = await importTypeScript(t, 'src/lib/videoUploadTask.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/api': api,
        'src/lib/idempotentRequests': idempotency,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/utils/taskTusUpload': transport,
    });

    return {
        uploads,
        task: (options = {}) =>
            new VideoUploadTask({
                ownerId: 'owner',
                label: 'Upload video',
                file: new File(['video'], 'clip.mp4', {
                    type: 'video/mp4',
                }),
                ...options,
            }),
        announce(index, url = 'https://hud.test/tus/files/upload-id') {
            uploads[index].url = url;
            uploads[index].options.onUploadUrlAvailable();
        },
        setOwner(value) {
            ownerId = value;
        },
        setToken(value) {
            token = value;
        },
    };
}

test('empty files fail before transport creation', async (t) => {
    const f = await fixture(t);

    assert.throws(() => f.task({ file: new File([], 'empty.mp4') }), { status: 400 });
    assert.equal(f.uploads.length, 0);
});

test('publishes progress, early availability, and completion', async (t) => {
    const f = await fixture(t);
    const available = [];
    const completed = [];
    const task = f.task({
        onUploadAvailable: (id) => available.push(id),
        onCompleted: (result) => completed.push(result),
    });

    assert.equal(isReadonly(task.uploadState), true);

    const attempt = task.retryOrResume();
    await nextTurn();

    f.announce(0);
    f.announce(0);
    f.uploads[0].options.onProgress(2, 5);

    assert.deepEqual(available, ['upload-id']);
    assert.equal(task.uploadState.uploadId, 'upload-id');
    assert.equal(task.state.status, 'running');
    assert.deepEqual(task.state.progress, {
        completed: 2,
        total: 5,
    });

    f.uploads[0].options.onSuccess();

    const result = await attempt;
    assert.deepEqual(result, {
        uploadId: 'upload-id',
        resumed: false,
    });
    assert.deepEqual(completed, [result]);
    assert.equal(task.state.status, 'completed');
});

test('retry uses the exact URL without discovery or replacement', async (t) => {
    const f = await fixture(t);
    const available = [];
    const task = f.task({
        onUploadAvailable: (id) => available.push(id),
    });

    const firstAttempt = task.retryOrResume();
    await nextTurn();

    assert.equal(f.uploads[0].options.uploadUrl, null);
    assert.equal(f.uploads[0].options.storeFingerprintForResuming, false);
    assert.equal(f.uploads[0].options.removeFingerprintOnSuccess, false);

    f.announce(0);
    assert.equal(f.uploads[0].options.endpoint, null);

    await task.pause();
    await firstAttempt;

    const secondAttempt = task.retryOrResume();
    await nextTurn();

    const upload = f.uploads[1];
    assert.equal(upload.options.uploadUrl, 'https://hud.test/tus/files/upload-id');
    assert.equal(upload.options.endpoint, null);
    assert.deepEqual(upload.options.retryDelays, [0, 1000, 3000, 5000, 10000, 20000]);

    f.announce(1);
    upload.options.onSuccess();

    assert.deepEqual(await secondAttempt, {
        uploadId: 'upload-id',
        resumed: true,
    });
    assert.deepEqual(available, ['upload-id']);
});

test('reads the token for each request and detects account changes', async (t) => {
    const f = await fixture(t);
    const task = f.task();
    const attempt = task.retryOrResume();
    await nextTurn();

    const headers = [];
    const request = {
        getMethod: () => 'PATCH',
        setHeader: (...args) => headers.push(args),
    };
    const upload = f.uploads[0];

    upload.options.onBeforeRequest(request);
    f.setToken('refreshed-token');
    upload.options.onBeforeRequest(request);

    assert.deepEqual(headers, [
        ['Authorization', 'Bearer first-token'],
        ['Authorization', 'Bearer refreshed-token'],
    ]);

    f.setOwner('another-owner');
    assert.throws(() => upload.options.onBeforeRequest(request), { name: 'AbortError' });
    await attempt;

    assert.equal(task.state.status, 'blocked');
    assert.equal(task.failure.status, 401);
    assert.deepEqual(upload.aborts, [false]);
});

test('cancellation waits for cleanup and suppresses late callbacks', async (t) => {
    const cleanup = deferred();
    const f = await fixture(t, {
        abortPromise: cleanup.promise,
    });
    const completed = [];
    const task = f.task({
        onCompleted: (result) => completed.push(result),
    });

    const attempt = task.retryOrResume();
    await nextTurn();

    f.announce(0);
    f.uploads[0].options.onProgress(2, 5);

    const cancellation = task.cancel();

    f.uploads[0].options.onProgress(5, 5);
    f.uploads[0].options.onSuccess();
    await nextTurn();

    assert.equal(task.state.status, 'cancelling');
    assert.deepEqual(task.state.progress, {
        completed: 2,
        total: 5,
    });
    assert.deepEqual(completed, []);

    cleanup.resolve();
    await cancellation;
    await attempt;

    assert.equal(task.state.status, 'cancelled');
    assert.deepEqual(f.uploads[0].aborts, [false]);
    assert.deepEqual(completed, []);
});

for (const [status, expected] of [
    [0, 'waiting'],
    [408, 'waiting'],
    [409, 'waiting'],
    [423, 'waiting'],
    [429, 'waiting'],
    [503, 'waiting'],
    [401, 'blocked'],
    [403, 'blocked'],
    [400, 'failed'],
    [404, 'failed'],
    [410, 'failed'],
]) {
    test(`HTTP ${status} produces ${expected}`, async (t) => {
        const f = await fixture(t);
        const task = f.task();
        const attempt = task.retryOrResume();
        await nextTurn();

        f.uploads[0].options.onError(new DetailedError('Upload failed', status));
        await attempt;

        assert.equal(task.state.status, expected);
        assert.equal(task.failure.status, status);
    });
}

test('invalid locations produce permanent failures', async (t) => {
    const f = await fixture(t);
    const task = f.task();
    const attempt = task.retryOrResume();
    await nextTurn();

    f.announce(0, 'https://hud.test/tus/files/');
    await attempt;

    assert.equal(task.state.status, 'failed');
    assert.equal(task.failure.message, 'Upload has no location ID');
});

test('availability callback failure does not fail the upload', async (t) => {
    const warn = t.mock.method(console, 'warn', () => {});
    const f = await fixture(t);
    const task = f.task({
        onUploadAvailable: async () => {
            throw new Error('Navigation failed');
        },
    });

    const attempt = task.retryOrResume();
    await nextTurn();

    f.announce(0);
    await nextTurn();
    f.uploads[0].options.onSuccess();
    await attempt;

    assert.equal(task.state.status, 'completed');
    assert.equal(warn.mock.callCount(), 1);
});

function tusResponse(status, headers = {}) {
    return {
        getStatus: () => status,
        getHeader: (name) => headers[name],
        getBody: () => '',
        getUnderlyingObject: () => null,
    };
}

async function realTransport(t, respond) {
    const tus = await import('tus-js-client');
    const requests = [];
    const forbiddenStorage = () => {
        assert.fail('Task uploads must not use URL storage');
    };

    class Upload extends tus.Upload {
        constructor(file, options) {
            super(file, {
                ...options,
                urlStorage: {
                    findAllUploads: forbiddenStorage,
                    findUploadsByFingerprint: forbiddenStorage,
                    addUpload: forbiddenStorage,
                    removeUpload: forbiddenStorage,
                },
                fileReader: {
                    async openFile() {
                        return {
                            size: file.size,
                            async slice(start, end) {
                                return { value: file.slice(start, end), done: end >= file.size };
                            },
                            close() {},
                        };
                    },
                },
                httpStack: {
                    getName: () => 'test',
                    createRequest(method, url) {
                        const request = { method, url, headers: new Map(), body: null };
                        requests.push(request);

                        return {
                            getMethod: () => method,
                            getURL: () => url,
                            getHeader: (name) => request.headers.get(name),
                            getUnderlyingObject: () => null,
                            setHeader(name, value) {
                                request.headers.set(name, value);
                            },
                            setProgressHandler() {},
                            async abort() {},
                            async send(body) {
                                request.body = body;
                                return respond(request);
                            },
                        };
                    },
                },
            });
        }
    }

    const transport = await loadTransport(
        t,
        {
            Upload,
            DetailedError: tus.DetailedError,
        },
        {
            getAuthSubject: () => 'owner',
            getAccessToken: () => 'token',
        },
    );
    return { ...transport, requests };
}

test('real Tus never replaces a missing pinned upload or uses URL storage', async (t) => {
    for (const status of [404, 410]) {
        const transport = await realTransport(t, () => tusResponse(status));
        const uploadUrl = 'https://hud.test/tus/files/missing';

        await assert.rejects(
            transport.uploadVideoTus(new File(['video'], 'clip.mp4'), {
                ownerId: 'owner',
                uploadUrl,
                signal: new AbortController().signal,
                onCheckpoint: () => Promise.resolve(),
                onProgress() {
                    assert.fail('Missing uploads cannot report progress');
                },
                onUploadAvailable() {
                    assert.fail('Missing uploads cannot become available');
                },
            }),
            { status },
        );

        assert.deepEqual(
            transport.requests.map(({ method, url }) => ({ method, url })),
            [{ method: 'HEAD', url: uploadUrl }],
        );
    }
});

test('real Tus creates once and resumes from the confirmed offset after a lost PATCH response', async (t) => {
    const uploadUrl = 'https://hud.test/tus/files/created';
    const available = [];
    let accepted = '';
    let offset = 0;
    let dropResponse = true;
    const transport = await realTransport(t, async (request) => {
        assert.equal(request.headers.get('Authorization'), 'Bearer token');
        if (request.method === 'POST') {
            return tusResponse(201, { Location: uploadUrl });
        }
        assert.equal(request.url, uploadUrl);
        if (request.method === 'HEAD') {
            return tusResponse(200, { 'Upload-Offset': String(offset), 'Upload-Length': '5' });
        }
        assert.equal(request.method, 'PATCH');
        assert.equal(request.headers.get('Upload-Offset'), String(offset));
        const body = await request.body.text();
        if (dropResponse) {
            dropResponse = false;
            accepted = body.slice(0, 2);
            offset = 2;
            throw new Error('Response lost after partial acceptance');
        }
        accepted += body;
        offset += body.length;
        return tusResponse(204, { 'Upload-Offset': String(offset) });
    });

    const result = await transport.uploadVideoTus(new File(['video'], 'clip.mp4'), {
        ownerId: 'owner',
        uploadUrl: null,
        signal: new AbortController().signal,
        onCheckpoint: () => Promise.resolve(),
        onProgress() {},
        onUploadAvailable: (value) => available.push(value),
    });

    assert.equal(accepted, 'video');
    assert.deepEqual(
        transport.requests.map(({ method }) => method),
        ['POST', 'PATCH', 'HEAD', 'PATCH'],
    );
    assert.deepEqual(result, { uploadId: 'created', uploadUrl, resumed: true });
    assert.deepEqual(
        available.map(({ resumed }) => resumed),
        [false, true],
    );
});

test('real Tus waits for a durable creation URL before availability or PATCH', async (t) => {
    const commit = deferred();
    const checkpointStarted = deferred();
    const available = [];
    const transport = await realTransport(t, (request) => {
        if (request.method === 'POST') return tusResponse(201, { Location: '/tus/files/durable' });
        return tusResponse(204, { 'Upload-Offset': '5' });
    });
    const pending = transport.uploadVideoTus(new File(['video'], 'clip.mp4'), {
        ownerId: 'owner',
        uploadUrl: null,
        signal: new AbortController().signal,
        async onCheckpoint(url) {
            assert.equal(url, 'https://hud.test/tus/files/durable');
            checkpointStarted.resolve();
            await commit.promise;
        },
        onProgress() {},
        onUploadAvailable: (value) => available.push(value),
    });
    await checkpointStarted.promise;
    assert.deepEqual(
        transport.requests.map(({ method }) => method),
        ['POST'],
    );
    assert.deepEqual(available, []);
    commit.resolve();
    assert.equal((await pending).uploadId, 'durable');
    assert.deepEqual(
        transport.requests.map(({ method }) => method),
        ['POST', 'PATCH'],
    );
    assert.equal(available.length, 1);
});

test('a creation checkpoint failure preserves its error and never transfers bytes', async (t) => {
    const failure = new Error('Task storage failed');
    const transport = await realTransport(t, () =>
        tusResponse(201, { Location: '/tus/files/durable' }),
    );
    await assert.rejects(
        transport.uploadVideoTus(new File(['video'], 'clip.mp4'), {
            ownerId: 'owner',
            uploadUrl: null,
            signal: new AbortController().signal,
            onCheckpoint: () => Promise.reject(failure),
            onProgress() {},
            onUploadAvailable() {
                assert.fail('Uncommitted uploads must not be announced');
            },
        }),
        (error) => error === failure,
    );
    await nextTurn();
    assert.deepEqual(
        transport.requests.map(({ method }) => method),
        ['POST'],
    );
});
