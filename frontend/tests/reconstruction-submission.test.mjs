import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const submissions = [];
    const api = await importTypeScript(t, 'src/lib/api.ts', {
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/auth': {
            authFetch(url, init) {
                const gate = deferred();
                submissions.push({ url, init, gate });
                return gate.promise;
            },
        },
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: { global: { t: (key) => key } } },
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/api': api,
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
        submissions,
        invalidation,
        mutation: () => app.runWithContext(() => scope.run(useSubmitReconstructionMutation)),
    };
}

function variables(buildingId = 'existing-building') {
    return {
        uploadId: 'stored-upload',
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
    test(`submits an upload ID to the ${buildingId === null ? 'new' : 'existing'} building endpoint`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        assert.equal(mutation.isLoading.value, false);
        const input = variables(buildingId);
        const promise = mutation.mutateAsync(input);
        await nextTurn();
        assert.equal(mutation.isLoading.value, true);
        assert.equal(mutation.destinationBuildingId.value, null);
        assert.equal(f.submissions.length, 1);
        const request = f.submissions[0];
        assert.equal(
            request.url,
            buildingId === null
                ? 'https://hud.test/buildings/from-reconstruction/from-upload'
                : 'https://hud.test/buildings/existing-building/reconstructions/from-upload',
        );
        assert.equal(request.init.method, 'POST');
        assert.deepEqual(JSON.parse(request.init.body), {
            upload_id: input.uploadId,
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
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.errorMessage.value, '');
        assert.deepEqual(
            f.invalidation.mock.calls.map((call) => call.arguments[0]),
            expectedInvalidations(destination),
        );
    });

    test(`scheduling failure retains IDs for the ${buildingId === null ? 'new' : 'existing'} building`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const promise = mutation.mutateAsync(variables(buildingId));
        const failed = assert.rejects(promise, { status: 503 });
        await nextTurn();
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
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.errorMessage.value, 'Scheduling failed');
        assert.deepEqual(
            f.invalidation.mock.calls.map((call) => call.arguments[0]),
            expectedInvalidations(destination),
        );
    });
}

test('independent mutations settle their loading and destination state separately', async (t) => {
    const f = await fixture(t);
    const first = f.mutation();
    const second = f.mutation();
    const firstPromise = first.mutateAsync(variables('first'));
    const secondPromise = second.mutateAsync(variables('second'));
    const failed = assert.rejects(secondPromise, { message: 'Connection lost' });
    await nextTurn();
    assert.equal(first.isLoading.value, true);
    assert.equal(second.isLoading.value, true);
    f.submissions[1].gate.reject(new Error('Connection lost'));
    await failed;
    assert.equal(first.isLoading.value, true);
    assert.equal(second.isLoading.value, false);
    assert.equal(second.destinationBuildingId.value, null);
    respond(f.submissions[0], { id: 'reconstruction-id', building_id: 'first' });
    await firstPromise;
    assert.equal(first.isLoading.value, false);
    assert.equal(first.destinationBuildingId.value, 'first');
    assert.equal(second.destinationBuildingId.value, null);
});

for (const status of [404, 409, 422, 503]) {
    test(`HTTP ${status} without retained IDs allows retry without a destination`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const input = variables();
        const attempt = mutation.mutateAsync(input);
        const failure = assert.rejects(attempt, { status });
        await nextTurn();
        respond(f.submissions[0], { detail: 'Upload unavailable' }, status);
        await failure;
        assert.equal(mutation.destinationBuildingId.value, null);
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.errorMessage.value, 'Upload unavailable');
        assert.equal(f.invalidation.mock.callCount(), 0);
        const retry = mutation.mutateAsync(input);
        await nextTurn();
        assert.equal(mutation.isLoading.value, true);
        respond(f.submissions[1], { id: 'retry', building_id: 'existing-building' });
        await retry;
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.destinationBuildingId.value, 'existing-building');
        assert.equal(mutation.errorMessage.value, '');
    });
}

test('a retained building remains available when reconstruction persistence fails', async (t) => {
    const f = await fixture(t);
    const mutation = f.mutation();
    const promise = mutation.mutateAsync(variables(null));
    const failure = assert.rejects(promise, { status: 503 });
    await nextTurn();
    respond(
        f.submissions[0],
        {
            detail: {
                message: 'Reconstruction database is unavailable',
                building_id: 'retained-building',
            },
        },
        503,
    );
    await failure;
    assert.equal(mutation.isLoading.value, false);
    assert.equal(mutation.destinationBuildingId.value, 'retained-building');
    assert.deepEqual(
        f.invalidation.mock.calls.map((call) => call.arguments[0]),
        expectedInvalidations('retained-building'),
    );
});

test('cache refresh failure does not change a successful submission', async (t) => {
    const f = await fixture(t);
    const warn = t.mock.method(console, 'warn', () => {});
    f.invalidation.mock.mockImplementation(() => Promise.reject(new Error('Refresh failed')));
    const mutation = f.mutation();
    const promise = mutation.mutateAsync(variables());
    await nextTurn();
    respond(f.submissions[0], { id: 'reconstruction-id', building_id: 'existing-building' });
    await promise;
    assert.equal(mutation.isLoading.value, false);
    assert.equal(mutation.error.value, null);
    assert.equal(mutation.destinationBuildingId.value, 'existing-building');
    assert.equal(warn.mock.callCount(), 1);
});
