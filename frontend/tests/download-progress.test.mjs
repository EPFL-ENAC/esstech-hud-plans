import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import * as vue from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';
import { downloadFixture } from './helpers/downloads.mjs';

async function fixture(t, engine) {
    const progress = await importTypeScript(t, 'src/queries/downloadProgress.ts', {
        vue: import.meta.resolve('vue'),
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test/api' },
        'src/lib/api': { ApiError: class extends Error {}, requestJson() {} },
        'src/lib/downloads/resumableDownload': { ResumableDownload: engine ?? class {} },
    });
    const requests = [];
    function request(buildingId, reconstructionId, signal, onProgress) {
        const gate = deferred();
        requests.push({ buildingId, reconstructionId, signal, onProgress, gate });
        return gate.promise;
    }
    const queries = await importTypeScript(t, 'src/queries/reconstructions.ts', {
        vue: import.meta.resolve('vue'),
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/composables/useDocumentVisibility': { useDocumentVisibility() {} },
        'src/lib/auth': { getAuthSubject: () => 'test-owner' },
        'src/queries/downloadProgress': progress,
        'src/lib/buildings': engine
            ? buildings
            : {
                  ...buildings,
                  getReconstructionSplat: request,
                  getReconstructionVideo: request,
              },
    });
    const app = vue.createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, {
        plugins: [progress.PiniaColadaDownloadProgress()],
        queryOptions: { gcTime: Infinity },
    });
    const cache = app.runWithContext(() => useQueryCache());
    const scope = vue.effectScope();
    t.after(() => {
        cache.cancelQueries({});
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        requests,
        start(id, kind = 'splat') {
            const reconstructionId = vue.ref(id);
            const query = app.runWithContext(() =>
                scope.run(() =>
                    kind === 'splat'
                        ? queries.useReconstructionSplatQuery(vue.ref('building'), reconstructionId)
                        : queries.useReconstructionVideoQuery(
                              vue.ref('building'),
                              reconstructionId,
                          ),
                ),
            );
            return { query, reconstructionId };
        },
    };
}

test('same-key consumers share progress and distinct downloads remain independent', async (t) => {
    const f = await fixture(t);
    const a = f.start('a');
    const a2 = f.start('a');
    const b = f.start('b');
    const video = f.start('a', 'video');
    await nextTurn();
    assert.equal(f.requests.length, 2);
    f.requests[0].onProgress({ loaded: 3, total: 6 });
    assert.deepEqual(a.query.downloadProgress.value, { loaded: 3, total: 6 });
    assert.deepEqual(a2.query.downloadProgress.value, { loaded: 3, total: 6 });
    assert.equal(b.query.downloadProgress.value, null);
    assert.equal(video.query.downloadProgress.value, null);

    a.reconstructionId.value = 'b';
    await vue.nextTick();
    assert.equal(a.query.downloadProgress.value, null);
    assert.deepEqual(a2.query.downloadProgress.value, { loaded: 3, total: 6 });
    f.requests[1].onProgress({ loaded: 4, total: 8 });
    assert.deepEqual(a.query.downloadProgress.value, { loaded: 4, total: 8 });
    assert.deepEqual(b.query.downloadProgress.value, { loaded: 4, total: 8 });
    for (const request of f.requests) request.gate.resolve(new ArrayBuffer(0));
    await nextTurn();
});

test('refetch resets progress and ignores callbacks from the superseded attempt', async (t) => {
    const f = await fixture(t);
    const { query } = f.start('a');
    await nextTurn();
    f.requests[0].onProgress({ loaded: 3, total: 6 });
    const retry = query.refetch();
    await nextTurn();
    assert.equal(f.requests[0].signal.aborted, true);
    assert.equal(query.downloadProgress.value, null);
    f.requests[0].onProgress({ loaded: 6, total: 6 });
    assert.equal(query.downloadProgress.value, null);
    f.requests[1].onProgress({ loaded: 2, total: 6 });
    assert.deepEqual(query.downloadProgress.value, { loaded: 2, total: 6 });
    f.requests[1].gate.resolve(new ArrayBuffer(6));
    await retry;
    f.requests[0].gate.resolve(new ArrayBuffer(3));
    await nextTurn();
    assert.equal(query.data.value.byteLength, 6);
});

test('a stalled real download becomes a retryable Colada error and retry succeeds', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: Date.now() });
    const engine = await downloadFixture(t);
    engine.setFetch(() => new Promise(() => {}));
    const f = await fixture(t, engine.ResumableDownload);
    const { query } = f.start('a');
    await nextTurn();
    assert.equal(query.state.value.status, 'pending');
    assert.equal(query.asyncStatus.value, 'loading');
    t.mock.timers.tick(60_000);
    await nextTurn();
    assert.equal(query.state.value.status, 'error');
    assert.equal(query.asyncStatus.value, 'idle');
    assert.equal(query.error.value.name, 'TimeoutError');
    engine.setFetch(() => new Response(new Uint8Array([1, 2, 3])));
    await query.refetch();
    assert.equal(query.state.value.status, 'success');
    assert.equal(query.error.value, null);
    assert.equal(query.data.value.byteLength, 3);
    assert.deepEqual(query.downloadProgress.value, { loaded: 3, total: 3 });
});
