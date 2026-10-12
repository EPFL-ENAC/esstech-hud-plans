import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope, isReadonly } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const uploads = [];
    const submissions = [];
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: { global: { t: (key) => key } } },
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/auth': {
            authFetch(url, init) {
                const gate = deferred();
                submissions.push({ url, init, gate });
                return gate.promise;
            },
        },
        'src/lib/utils/resumableDownload': { downloadResumable() {} },
    });
    const { useSubmitReconstructionMutation } = await importTypeScript(
        t,
        'src/mutations/reconstructions.ts',
        {
            vue: import.meta.resolve('vue'),
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'src/lib/auth': { getAuthSubject: () => 'test-user' },
            'src/lib/buildings': buildings,
            'src/lib/utils/tusUpload': {
                uploadVideoResumable(file, options) {
                    const gate = deferred();
                    uploads.push({ file, options, gate });
                    return gate.promise;
                },
            },
        },
    );
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, { mutationOptions: { gcTime: Infinity } });
    const scope = effectScope();
    const cache = app.runWithContext(() => useQueryCache());
    const invalidation = t.mock.method(cache, 'invalidateQueries', () => Promise.resolve());
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        uploads,
        submissions,
        invalidation,
        mutation: () => app.runWithContext(() => scope.run(useSubmitReconstructionMutation)),
    };
}

function variables(buildingId = 'existing-building') {
    return {
        video: { name: 'scan.mp4' },
        settings: { ffmpeg: { fps: 4 } },
        ...(buildingId === null
            ? {
                  buildingId: null,
                  building: { name: 'New building', latitude: null, longitude: null },
              }
            : { buildingId }),
    };
}

function respond(submission, body, status = 202) {
    submission.gate.resolve(new Response(JSON.stringify(body), { status }));
}

function expectedInvalidations(buildingId) {
    const root = ['buildings', 'test-user'];
    return [
        { key: [...root, 'all'] },
        { key: [...root, 'list'] },
        { key: [...root, 'locations'] },
        { key: [...root, 'detail', buildingId], exact: true },
        { key: [...root, 'detail', buildingId, 'reconstructions', 'list'] },
    ];
}

for (const buildingId of ['existing-building', null]) {
    test(`submission lifecycle awaits the ${buildingId === null ? 'new' : 'existing'} building endpoint`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        assert.equal(isReadonly(mutation.submissionState), true);
        assert.deepEqual(mutation.submissionState.value, { phase: 'idle' });
        const input = variables(buildingId);
        const promise = mutation.mutateAsync(input);
        await nextTurn();
        assert.deepEqual(mutation.submissionState.value, {
            phase: 'uploading',
            progress: null,
            resumed: false,
        });
        const upload = f.uploads[0];
        assert.equal(upload.file, input.video);
        upload.options.onProgress({ loaded: 12, total: 0 });
        upload.options.onResumed();
        assert.deepEqual(mutation.submissionState.value, {
            phase: 'uploading',
            progress: { loaded: 12, total: 0 },
            resumed: true,
        });
        upload.gate.resolve({ uploadId: 'upload-id', resumed: true });
        await nextTurn();
        assert.deepEqual(mutation.submissionState.value, { phase: 'submitting' });
        assert.equal(mutation.isLoading.value, true);
        upload.options.onProgress({ loaded: 100, total: 100 });
        upload.options.onResumed();
        assert.deepEqual(mutation.submissionState.value, { phase: 'submitting' });
        const request = f.submissions[0];
        assert.equal(
            request.url,
            buildingId === null
                ? 'https://hud.test/buildings/from-reconstruction/resumable'
                : 'https://hud.test/buildings/existing-building/reconstructions/resumable',
        );
        assert.deepEqual(JSON.parse(request.init.body), {
            tus_upload_id: 'upload-id',
            settings: input.settings,
            ...(buildingId === null ? { building: input.building } : {}),
        });
        const destination = buildingId ?? 'created-building';
        const reconstruction = { id: 'reconstruction-id', building_id: destination };
        respond(
            request,
            buildingId === null
                ? { building: { id: destination }, reconstruction }
                : reconstruction,
        );
        assert.deepEqual(await promise, reconstruction);
        assert.deepEqual(mutation.submissionState.value, { phase: 'idle' });
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.errorMessage.value, '');
        assert.deepEqual(
            f.invalidation.mock.calls.map((call) => call.arguments[0]),
            expectedInvalidations(destination),
        );
        upload.options.onProgress({ loaded: 200, total: 200 });
        assert.deepEqual(mutation.submissionState.value, { phase: 'idle' });
    });
}

test('independent mutation instances never share progress or resumed state', async (t) => {
    const f = await fixture(t);
    const first = f.mutation();
    const second = f.mutation();
    const firstPromise = first.mutateAsync(variables('first'));
    const secondPromise = second.mutateAsync(variables('second'));
    await nextTurn();
    const [firstUpload, secondUpload] = f.uploads;
    firstUpload.options.onProgress({ loaded: 25, total: 100 });
    firstUpload.options.onResumed();
    secondUpload.options.onProgress({ loaded: 10, total: 200 });
    assert.deepEqual(first.submissionState.value, {
        phase: 'uploading',
        progress: { loaded: 25, total: 100 },
        resumed: true,
    });
    assert.deepEqual(second.submissionState.value, {
        phase: 'uploading',
        progress: { loaded: 10, total: 200 },
        resumed: false,
    });
    const failed = assert.rejects(secondPromise, { message: 'Connection lost' });
    secondUpload.gate.reject(new Error('Connection lost'));
    await failed;
    assert.deepEqual(second.submissionState.value, { phase: 'idle' });
    assert.equal(first.submissionState.value.phase, 'uploading');
    assert.equal(f.submissions.length, 0);
    firstUpload.gate.resolve({ uploadId: 'first-upload' });
    await nextTurn();
    respond(f.submissions[0], { id: 'reconstruction-id', building_id: 'first' });
    await firstPromise;
});

test('upload failure never submits, resets state, and allows a fresh attempt', async (t) => {
    const f = await fixture(t);
    const mutation = f.mutation();
    const promise = mutation.mutateAsync(variables());
    const failed = assert.rejects(promise, { name: 'AbortError' });
    await nextTurn();
    f.uploads[0].options.onResumed();
    f.uploads[0].gate.reject(new DOMException('Aborted', 'AbortError'));
    await failed;
    assert.deepEqual(mutation.submissionState.value, { phase: 'idle' });
    assert.equal(f.submissions.length, 0);
    assert.equal(f.invalidation.mock.callCount(), 0);
    const retry = mutation.mutateAsync(variables());
    await nextTurn();
    assert.deepEqual(mutation.submissionState.value, {
        phase: 'uploading',
        progress: null,
        resumed: false,
    });
    f.uploads[1].gate.resolve({ uploadId: 'retry-upload' });
    await nextTurn();
    respond(f.submissions[0], { id: 'reconstruction-id', building_id: 'existing-building' });
    await retry;
});

for (const buildingId of ['existing-building', null]) {
    test(`submission failure retains IDs and invalidates the ${buildingId === null ? 'new' : 'existing'} building`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const promise = mutation.mutateAsync(variables(buildingId));
        const failed = assert.rejects(promise, { status: 503 });
        await nextTurn();
        f.uploads[0].gate.resolve({ uploadId: 'upload-id' });
        await nextTurn();
        assert.equal(mutation.submissionState.value.phase, 'submitting');
        const destination = buildingId ?? 'retained-building';
        respond(
            f.submissions[0],
            {
                detail: {
                    message: 'Scheduling failed',
                    reconstruction_id: 'retained-reconstruction',
                    ...(buildingId === null ? { building_id: destination } : {}),
                },
            },
            503,
        );
        await failed;
        assert.deepEqual(mutation.submissionState.value, { phase: 'idle' });
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.errorMessage.value, 'Scheduling failed');
        assert.deepEqual(
            f.invalidation.mock.calls.map((call) => call.arguments[0]),
            expectedInvalidations(destination),
        );
    });
}

test('cache refresh failure does not change a successful submission', async (t) => {
    const f = await fixture(t);
    const warn = t.mock.method(console, 'warn', () => {});
    f.invalidation.mock.mockImplementation(() => Promise.reject(new Error('Refresh failed')));
    const mutation = f.mutation();
    const promise = mutation.mutateAsync(variables());
    await nextTurn();
    f.uploads[0].gate.resolve({ uploadId: 'upload-id' });
    await nextTurn();
    respond(f.submissions[0], { id: 'reconstruction-id', building_id: 'existing-building' });
    await promise;
    assert.equal(mutation.error.value, null);
    assert.equal(mutation.destinationBuildingId.value, 'existing-building');
    assert.equal(warn.mock.callCount(), 1);
});
