import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';
import { MemoryLocalUploadsRegistry } from './helpers/localUploadsRegistry.mjs';

class ApiError extends Error {
    constructor(message, status, body) {
        super(message);
        this.status = status;
        this.body = body;
    }
}

async function fixture(t) {
    let subject = 'user-a';
    const uploads = new MemoryLocalUploadsRegistry();
    const scheduled = [];
    const queue = {
        submit(task, options) {
            assert.deepEqual(options, { waitForFirstTry: false });
            const gate = deferred();
            scheduled.push({ task, gate });
            return gate.promise;
        },
    };
    const { useScheduleVideoUploadMutation } = await importTypeScript(
        t,
        'src/mutations/uploads.ts',
        {
            vue: import.meta.resolve('vue'),
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'src/lib/api': { ApiError },
            'src/lib/auth': { getAuthSubject: () => subject },
            'src/lib/localUploadsRegistry': {
                LocalUploadsRegistry: class {
                    constructor() {
                        return uploads;
                    }
                },
            },
            'src/lib/videoUploadTask': {
                VideoUploadTask: class {
                    constructor(options) {
                        this.id = crypto.randomUUID();
                        this.options = options;
                    }
                },
            },
            'src/stores/networkDependentTasks': {
                useNetworkDependentTasks: () => queue,
            },
            'src/lib/utils/tusUpload': {
                uploadVideoResumable() {
                    assert.fail('Preparation must not directly transfer files');
                },
            },
        },
    );
    const app = createApp({});
    const pinia = createPinia();
    const scope = effectScope();
    app.use(pinia);
    app.use(PiniaColada, { mutationOptions: { gcTime: Infinity } });
    const cache = app.runWithContext(() => useQueryCache());
    const invalidation = t.mock.method(cache, 'invalidateQueries', () => Promise.resolve());
    const mutation = app.runWithContext(() => scope.run(useScheduleVideoUploadMutation));
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        uploads,
        scheduled,
        mutation,
        scope,
        invalidation,
        setSubject(value) {
            subject = value;
        },
    };
}

function video() {
    return new File(['video'], 'scan.mp4', { type: 'video/mp4', lastModified: 42 });
}

test('preparation waits for registration and durable task admission', async (t) => {
    const f = await fixture(t);
    const registration = deferred();
    const create = f.uploads.create.bind(f.uploads);
    const file = video();
    t.mock.method(f.uploads, 'create', async (...args) => {
        await registration.promise;
        return create(...args);
    });
    let settled = false;
    const preparation = f.mutation.mutateAsync({ file }).then((result) => {
        settled = true;
        return result;
    });
    await nextTurn();
    assert.equal(settled, false);
    assert.equal(f.mutation.isLoading.value, true);
    assert.equal(f.scheduled.length, 0);
    registration.resolve();
    await nextTurn();
    assert.equal(f.scheduled.length, 1);
    assert.equal(settled, false);
    assert.equal(f.mutation.isLoading.value, true);
    const { task, gate } = f.scheduled[0];
    const record = await f.uploads.get('user-a', task.options.localUploadId);
    assert.equal(record.remote, null);
    assert.equal(task.options.ownerId, 'user-a');
    assert.equal(task.options.label, file.name);
    assert.equal(task.options.uploads, f.uploads);
    assert.equal(f.invalidation.mock.callCount(), 0);
    gate.resolve({ status: 'queued', taskId: task.id });
    const result = await preparation;
    assert.deepEqual(result, { localUploadId: record.id, taskId: task.id });
    assert.notEqual(result.localUploadId, result.taskId);
    assert.equal(f.mutation.isLoading.value, false);
    assert.equal(await (await f.uploads.getFile('user-a', record.id)).text(), 'video');
});

test('registration failure prevents task admission', async (t) => {
    const f = await fixture(t);
    const failure = new Error('File storage unavailable');
    t.mock.method(f.uploads, 'create', async () => {
        throw failure;
    });
    await assert.rejects(f.mutation.mutateAsync({ file: video() }), (error) => error === failure);
    assert.equal(f.scheduled.length, 0);
    assert.equal(f.mutation.isLoading.value, false);
});

test('admission failure preserves the registered upload', async (t) => {
    const f = await fixture(t);
    const failure = new Error('Task storage unavailable');
    const preparation = f.mutation.mutateAsync({ file: video() });
    const rejected = assert.rejects(preparation, (error) => error === failure);
    await nextTurn();
    const { task, gate } = f.scheduled[0];
    gate.reject(failure);
    await rejected;
    assert.equal(
        await (await f.uploads.getFile('user-a', task.options.localUploadId)).text(),
        'video',
    );
    assert.equal((await f.uploads.get('user-a', task.options.localUploadId)).remote, null);
});

for (const subject of [null, 'user-b']) {
    test(`a missing or changed account ${subject} prevents preparation`, async (t) => {
        const f = await fixture(t);
        f.setSubject(subject);
        await assert.rejects(f.mutation.mutateAsync({ file: video() }), { status: 401 });
        assert.deepEqual(await f.uploads.list('user-a'), []);
        assert.equal(f.scheduled.length, 0);
    });
}

test('an account change during registration prevents scheduling', async (t) => {
    const f = await fixture(t);
    const registration = deferred();
    const create = f.uploads.create.bind(f.uploads);
    t.mock.method(f.uploads, 'create', async (...args) => {
        await registration.promise;
        return create(...args);
    });
    const rejected = assert.rejects(f.mutation.mutateAsync({ file: video() }), { status: 401 });
    await nextTurn();
    f.setSubject('user-b');
    registration.resolve();
    await rejected;
    assert.equal(f.scheduled.length, 0);
    assert.equal((await f.uploads.list('user-a')).length, 1);
    assert.deepEqual(await f.uploads.list('user-b'), []);
});

test('empty files cannot be scheduled', async (t) => {
    const f = await fixture(t);
    await assert.rejects(f.mutation.mutateAsync({ file: new File([], 'empty.mp4') }), {
        status: 400,
    });
    assert.equal(f.scheduled.length, 0);
    assert.deepEqual(await f.uploads.list('user-a'), []);
});

test('availability forwards the remote ID after preparation and refreshes uploads', async (t) => {
    const f = await fixture(t);
    const available = [];
    const callback = deferred();
    const preparation = f.mutation.mutateAsync({
        file: video(),
        onUploadAvailable: async (uploadId) => {
            available.push(uploadId);
            await callback.promise;
        },
    });
    await nextTurn();
    const { task, gate } = f.scheduled[0];
    gate.resolve({ status: 'queued', taskId: task.id });
    const result = await preparation;
    let callbackSettled = false;
    const availability = task.options.onUploadAvailable('remote-upload').then(() => {
        callbackSettled = true;
    });
    await nextTurn();
    assert.deepEqual(available, ['remote-upload']);
    assert.equal(callbackSettled, false);
    assert.deepEqual(f.mutation.data.value, result);
    assert.equal(f.mutation.isLoading.value, false);
    assert.deepEqual(f.invalidation.mock.calls[0].arguments, [{ key: ['uploads', 'user-a'] }]);
    callback.resolve();
    await availability;
    task.options.onCompleted();
    assert.equal(f.invalidation.mock.callCount(), 2);
});

test('callback and cache failures cannot change a prepared result', async (t) => {
    const f = await fixture(t);
    const callbackFailure = new Error('Navigation failed');
    t.mock.method(console, 'warn', () => {});
    f.invalidation.mock.mockImplementation(() => Promise.reject(new Error('Cache unavailable')));
    const preparation = f.mutation.mutateAsync({
        file: video(),
        onUploadAvailable: async () => {
            throw callbackFailure;
        },
    });
    await nextTurn();
    const { task, gate } = f.scheduled[0];
    gate.resolve({ status: 'queued', taskId: task.id });
    const result = await preparation;
    // VideoUploadTask catches callback rejection at its callback boundary.
    await assert.rejects(
        task.options.onUploadAvailable('remote-upload'),
        (error) => error === callbackFailure,
    );
    task.options.onCompleted();
    await nextTurn();
    assert.deepEqual(f.mutation.data.value, result);
    assert.equal(f.mutation.error.value, null);
    assert.equal(f.mutation.isLoading.value, false);
});

test('page disposal does not cancel preparation or scheduled callbacks', async (t) => {
    const f = await fixture(t);
    const available = [];
    const preparation = f.mutation.mutateAsync({
        file: video(),
        onUploadAvailable: (uploadId) => {
            available.push(uploadId);
        },
    });
    await nextTurn();
    const { task, gate } = f.scheduled[0];
    f.scope.stop();
    gate.resolve({ status: 'queued', taskId: task.id });
    const result = await preparation;
    await task.options.onUploadAvailable('remote-upload');
    assert.equal(result.taskId, task.id);
    assert.deepEqual(available, ['remote-upload']);
});
