import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope, isReadonly } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

class ApiError extends Error {
    constructor(message, status, body) {
        super(message);
        this.status = status;
        this.body = body;
    }
}

async function fixture(t) {
    const uploads = [];
    let subject = 'user-a';
    const { useUploadVideoMutation } = await importTypeScript(t, 'src/mutations/uploads.ts', {
        vue: import.meta.resolve('vue'),
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/lib/api': { ApiError },
        'src/lib/auth': { getAuthSubject: () => subject },
        'src/lib/utils/tusUpload': {
            uploadVideoResumable(file, options) {
                const gate = deferred();
                uploads.push({ file, options, gate });
                return gate.promise;
            },
        },
    });
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, { mutationOptions: { gcTime: Infinity } });
    const cache = app.runWithContext(() => useQueryCache());
    const invalidation = t.mock.method(cache, 'invalidateQueries', () => Promise.resolve());
    const scopes = [];
    t.after(() => {
        scopes.forEach((scope) => scope.stop());
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        uploads,
        invalidation,
        setSubject(value) {
            subject = value;
        },
        mutation() {
            const scope = effectScope();
            scopes.push(scope);
            return {
                scope,
                mutation: app.runWithContext(() => scope.run(useUploadVideoMutation)),
            };
        },
    };
}

const file = { name: 'scan.mp4', size: 100 };

test('upload mutation reports progress/resume and invalidates only its user upload lists', async (t) => {
    const f = await fixture(t);
    const { mutation } = f.mutation();
    assert.equal(isReadonly(mutation.transferState), true);
    const promise = mutation.mutateAsync({ file });
    await nextTurn();
    assert.equal(mutation.isLoading.value, true);
    const upload = f.uploads[0];
    assert.equal(upload.options.subject, 'user-a');
    upload.options.onProgress({ loaded: 40, total: 100 });
    upload.options.onResumed();
    assert.deepEqual(mutation.transferState.value, {
        phase: 'uploading',
        progress: { loaded: 40, total: 100 },
        resumed: true,
    });
    upload.options.onUploadAvailable();
    assert.deepEqual(f.invalidation.mock.calls[0].arguments, [
        { key: ['uploads', 'user-a', 'list'] },
    ]);
    upload.gate.resolve({ uploadId: 'uuid-hex', resumed: true });
    assert.deepEqual(await promise, { uploadId: 'uuid-hex', resumed: true });
    assert.equal(mutation.isLoading.value, false);
    assert.deepEqual(mutation.transferState.value, { phase: 'idle' });
    assert.equal(f.invalidation.mock.callCount(), 2);
});

test('disposed pages leave transfers running and new instances have independent state', async (t) => {
    const f = await fixture(t);
    const first = f.mutation();
    const a = first.mutation.mutateAsync({ file });
    await nextTurn();
    first.scope.stop();
    const second = f.mutation();
    const b = second.mutation.mutateAsync({ file: { name: 'second.mp4', size: 200 } });
    await nextTurn();
    f.uploads[0].options.onProgress({ loaded: 50, total: 100 });
    f.uploads[1].options.onProgress({ loaded: 20, total: 200 });
    assert.equal(first.mutation.transferState.value.progress.loaded, 50);
    assert.equal(second.mutation.transferState.value.progress.loaded, 20);
    f.uploads[0].gate.resolve({ uploadId: 'a', resumed: false });
    await a;
    assert.equal(second.mutation.isLoading.value, true);
    f.uploads[1].gate.resolve({ uploadId: 'b', resumed: false });
    await b;
    assert.equal(first.mutation.data.value.uploadId, 'a');
    assert.equal(second.mutation.data.value.uploadId, 'b');
});

test('failure settles the pending-row cache and retry uses the selected file again', async (t) => {
    const f = await fixture(t);
    const { mutation } = f.mutation();
    const first = mutation.mutateAsync({ file });
    await nextTurn();
    f.uploads[0].gate.reject(new ApiError('Unavailable', 503, null));
    await assert.rejects(first, { status: 503 });
    assert.deepEqual(mutation.transferState.value, { phase: 'idle' });
    assert.equal(f.invalidation.mock.callCount(), 1);
    const retry = mutation.mutateAsync({ file });
    await nextTurn();
    assert.equal(f.uploads[1].file, file);
    f.uploads[1].gate.resolve({ uploadId: 'same-id', resumed: true });
    await retry;
    assert.equal(mutation.error.value, null);
});

test('cache refresh failure cannot change a successful transfer', async (t) => {
    const f = await fixture(t);
    t.mock.method(console, 'warn', () => {});
    f.invalidation.mock.mockImplementation(() => Promise.reject(new Error('Cache unavailable')));
    const { mutation } = f.mutation();
    const promise = mutation.mutateAsync({ file });
    await nextTurn();
    f.uploads[0].options.onUploadAvailable();
    f.uploads[0].gate.resolve({ uploadId: 'complete', resumed: false });
    assert.equal((await promise).uploadId, 'complete');
    await nextTurn();
    assert.equal(mutation.error.value, null);
});

for (const subject of [null, 'user-b']) {
    test(`missing or changed subject ${subject} never starts a transfer`, async (t) => {
        const f = await fixture(t);
        const { mutation } = f.mutation();
        f.setSubject(subject);
        await assert.rejects(mutation.mutateAsync({ file }), { status: 401 });
        assert.equal(f.uploads.length, 0);
    });
}

test('empty files never start a transfer', async (t) => {
    const f = await fixture(t);
    const { mutation } = f.mutation();
    await assert.rejects(mutation.mutateAsync({ file: { name: 'empty.mp4', size: 0 } }), {
        status: 400,
    });
    assert.equal(f.uploads.length, 0);
});
