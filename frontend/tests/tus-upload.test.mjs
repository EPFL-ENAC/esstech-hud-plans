import assert from 'node:assert/strict';
import { getEventListeners } from 'node:events';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

class ApiError extends Error {
    constructor(message, status, body) {
        super(message);
        this.status = status;
        this.body = body;
    }
}

class DetailedError extends Error {
    originalResponse = { getStatus: () => 401 };
}

async function fixture(t, behavior = {}) {
    const lookup = deferred();
    const uploads = [];
    let token = 'first-token';
    class Upload {
        url = 'https://hud.test/tus/files/upload-id';
        starts = 0;
        resumes = [];
        aborts = [];
        constructor(file, options) {
            this.file = file;
            this.options = options;
            uploads.push(this);
        }
        findPreviousUploads() {
            if (behavior.lookupThrows) throw behavior.lookupThrows;
            return lookup.promise;
        }
        resumeFromPreviousUpload(previous) {
            this.resumes.push(previous);
            if (behavior.resumeThrows) throw behavior.resumeThrows;
        }
        start() {
            this.starts++;
            if (behavior.startThrows) throw behavior.startThrows;
        }
        abort(terminate) {
            this.aborts.push(terminate);
            if (behavior.abortThrows) throw behavior.abortThrows;
            return behavior.abortRejects
                ? Promise.reject(behavior.abortRejects)
                : Promise.resolve();
        }
    }
    const { uploadVideoResumable } = await importTypeScript(t, 'src/lib/utils/tusUpload.ts', {
        'tus-js-client': { Upload, DetailedError },
        'src/boot/api': { tusEndpoint: 'https://hud.test/tus/files/' },
        'src/lib/auth': { getAccessToken: () => token },
        'src/lib/buildings': { ApiError },
    });
    return {
        lookup,
        uploads,
        upload: (opts) => uploadVideoResumable({ name: 'scan.mp4' }, opts),
        setToken: (value) => (token = value),
    };
}

test('pre-aborted signals reject before constructing an upload', async (t) => {
    const f = await fixture(t);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(f.upload({ signal: controller.signal }), { name: 'AbortError' });
    assert.equal(f.uploads.length, 0);
});

for (const lookupFails of [false, true]) {
    test(`abort during lookup never starts or resumes (lookup fails: ${lookupFails})`, async (t) => {
        const f = await fixture(t);
        const controller = new AbortController();
        const progress = [];
        let resumes = 0;
        const promise = f.upload({
            signal: controller.signal,
            onProgress: (value) => progress.push(value),
            onResumed: () => resumes++,
        });
        controller.abort();
        await assert.rejects(promise, { name: 'AbortError' });
        if (lookupFails) f.lookup.reject(new Error('Storage unavailable'));
        else f.lookup.resolve([{ uploadUrl: 'previous-upload' }]);
        await nextTurn();
        const upload = f.uploads[0];
        upload.options.onProgress(10, 20);
        upload.options.onSuccess();
        upload.options.onError(new Error('Late error'));
        assert.equal(upload.starts, 0);
        assert.deepEqual(upload.resumes, []);
        assert.deepEqual(upload.aborts, [false]);
        assert.deepEqual(progress, []);
        assert.equal(resumes, 0);
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
    });
}

test('active abort pauses once and suppresses late callbacks', async (t) => {
    const f = await fixture(t);
    const controller = new AbortController();
    const progress = [];
    const promise = f.upload({
        signal: controller.signal,
        onProgress: (value) => progress.push(value),
    });
    f.lookup.resolve([]);
    await nextTurn();
    const upload = f.uploads[0];
    upload.options.onProgress(10, 0);
    controller.abort();
    controller.abort();
    await assert.rejects(promise, { name: 'AbortError' });
    upload.options.onProgress(20, 100);
    upload.options.onSuccess();
    upload.options.onError(new DetailedError('Late error'));
    assert.equal(upload.starts, 1);
    assert.deepEqual(upload.aborts, [false]);
    assert.deepEqual(progress, [{ loaded: 10, total: 0 }]);
});

for (const failure of ['abortThrows', 'abortRejects']) {
    test(`${failure} is logged without replacing AbortError or leaking rejection`, async (t) => {
        const cleanupError = new Error('Could not stop transport');
        const warn = t.mock.method(console, 'warn', () => {});
        const f = await fixture(t, { [failure]: cleanupError });
        const controller = new AbortController();
        const promise = f.upload({ signal: controller.signal });
        controller.abort();
        await assert.rejects(promise, { name: 'AbortError' });
        f.lookup.resolve([]);
        await nextTurn();
        assert.equal(warn.mock.callCount(), 1);
        assert.equal(warn.mock.calls[0].arguments[1], cleanupError);
        assert.equal(f.uploads[0].starts, 0);
    });
}

for (const outcome of ['success', 'error', 'missing-location']) {
    test(`${outcome} removes the abort listener and ignores later events`, async (t) => {
        const f = await fixture(t);
        const controller = new AbortController();
        const progress = [];
        const promise = f.upload({
            signal: controller.signal,
            onProgress: (value) => progress.push(value),
        });
        f.lookup.resolve([]);
        await nextTurn();
        const upload = f.uploads[0];
        assert.equal(getEventListeners(controller.signal, 'abort').length, 1);
        if (outcome === 'success') {
            upload.options.onSuccess();
            assert.deepEqual(await promise, { uploadId: 'upload-id', resumed: false });
        } else if (outcome === 'error') {
            upload.options.onError(new DetailedError('Unauthorized'));
            await assert.rejects(promise, { status: 401 });
        } else {
            upload.url = null;
            upload.options.onSuccess();
            await assert.rejects(promise, { message: 'Upload completed without a location' });
        }
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
        controller.abort();
        upload.options.onProgress(100, 100);
        upload.options.onSuccess();
        assert.deepEqual(upload.aborts, []);
        assert.deepEqual(progress, []);
    });
}

test('lookup failure falls back to one fresh upload', async (t) => {
    const f = await fixture(t);
    const promise = f.upload();
    f.lookup.reject(new Error('Storage unavailable'));
    await nextTurn();
    const upload = f.uploads[0];
    assert.equal(upload.starts, 1);
    assert.deepEqual(upload.resumes, []);
    upload.options.onSuccess();
    assert.deepEqual(await promise, { uploadId: 'upload-id', resumed: false });
});

for (const failure of ['startThrows', 'resumeThrows']) {
    test(`${failure} rejects without retrying startup and removes the listener`, async (t) => {
        const error = new Error('Startup failed');
        const f = await fixture(t, { [failure]: error });
        const controller = new AbortController();
        const promise = f.upload({ signal: controller.signal });
        f.lookup.resolve(failure === 'resumeThrows' ? [{}] : []);
        await assert.rejects(promise, (received) => received === error);
        assert.equal(f.uploads[0].starts, failure === 'startThrows' ? 1 : 0);
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
        controller.abort();
        assert.deepEqual(f.uploads[0].aborts, []);
    });
}

test('resuming retains transport settings and reads the token per request', async (t) => {
    const f = await fixture(t);
    let resumed = 0;
    const promise = f.upload({ onResumed: () => resumed++ });
    const previous = { uploadUrl: 'https://hud.test/tus/files/previous' };
    f.lookup.resolve([previous]);
    await nextTurn();
    const upload = f.uploads[0];
    assert.deepEqual(upload.resumes, [previous]);
    assert.equal(resumed, 1);
    assert.equal(upload.options.chunkSize, 64 * 1024 * 1024);
    assert.deepEqual(upload.options.retryDelays, [0, 1000, 3000, 5000, 10000, 20000]);
    assert.deepEqual(upload.options.metadata, { filename: 'scan.mp4', filetype: undefined });
    assert.equal(upload.options.removeFingerprintOnSuccess, true);
    const headers = [];
    const request = { setHeader: (...args) => headers.push(args) };
    upload.options.onBeforeRequest(request);
    f.setToken('refreshed-token');
    upload.options.onBeforeRequest(request);
    assert.deepEqual(headers, [
        ['Authorization', 'Bearer first-token'],
        ['Authorization', 'Bearer refreshed-token'],
    ]);
    upload.options.onSuccess();
    assert.deepEqual(await promise, { uploadId: 'upload-id', resumed: true });
});

test('abort from the resume callback prevents startup', async (t) => {
    const f = await fixture(t);
    const controller = new AbortController();
    const promise = f.upload({
        signal: controller.signal,
        onResumed: () => controller.abort(),
    });
    f.lookup.resolve([{}]);
    await assert.rejects(promise, { name: 'AbortError' });
    assert.equal(f.uploads[0].starts, 0);
});
