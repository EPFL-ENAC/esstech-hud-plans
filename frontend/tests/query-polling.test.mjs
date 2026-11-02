import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import * as vue from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada } from '@pinia/colada';
import { PiniaColadaAutoRefetch } from '@pinia/colada-plugin-auto-refetch';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, kind, initialSubject = 'user-a') {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: Date.now() });
    const previousDocument = globalThis.document;
    const document = new EventTarget();
    document.visibilityState = 'visible';
    globalThis.document = document;
    const activated = [];
    const deactivated = [];
    const requests = [];
    let subject = initialSubject;
    const offset = vue.ref(0);
    const buildingId = vue.ref('building-a');
    const reconstructionId = vue.ref('reconstruction-a');
    const reconstructionStatus = vue.ref(null);
    const search = vue.ref(null);

    function request(details) {
        const gate = deferred();
        requests.push({ ...details, gate });
        return gate.promise;
    }

    const visibility = await importTypeScript(t, 'src/composables/useDocumentVisibility.ts', {
        vue: import.meta.resolve('vue'),
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test/api' },
        'src/lib/api': { ApiError: class extends Error {}, requestJson() {} },
        'src/lib/utils/resumableDownload': { downloadResumable() {} },
    });
    const imports = {
        vue: {
            computed: vue.computed,
            ref: vue.ref,
            toValue: vue.toValue,
            watch: vue.watch,
            onMounted: vue.onMounted,
            onScopeDispose: vue.onScopeDispose,
            onActivated: (callback) => activated.push(callback),
            onDeactivated: (callback) => deactivated.push(callback),
        },
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/composables/useDocumentVisibility': visibility,
        'src/lib/auth': { getAuthSubject: () => subject },
        'src/lib/buildings': {
            ...buildings,
            listBuildings: (options) => request({ options }),
            listReconstructions: (buildingId, options) => request({ buildingId, options }),
            getReconstructionStep: (buildingId, reconstructionId, signal) =>
                request({ buildingId, reconstructionId, signal }),
        },
        'src/stores/splatDownload': { useSplatDownloadStore() {} },
        'src/stores/videoDownload': { useVideoDownloadStore() {} },
    };
    const queries = await importTypeScript(
        t,
        kind === 'buildings' ? 'src/queries/buildings.ts' : 'src/queries/reconstructions.ts',
        imports,
    );
    const app = vue.createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, {
        plugins: [PiniaColadaAutoRefetch()],
        queryOptions: { gcTime: Infinity },
    });
    const scope = vue.effectScope();
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
        if (previousDocument === undefined) delete globalThis.document;
        else globalThis.document = previousDocument;
    });

    return {
        offset,
        buildingId,
        reconstructionId,
        reconstructionStatus,
        search,
        requests,
        start() {
            return app.runWithContext(() =>
                scope.run(() => {
                    if (kind === 'buildings') {
                        return queries.useMyBuildingsQuery(offset, reconstructionStatus, search);
                    }
                    if (kind === 'reconstructions') {
                        return queries.useReconstructionsQuery(buildingId, offset);
                    }
                    return queries.useReconstructionStepQuery(buildingId, reconstructionId);
                }),
            );
        },
        stop: () => scope.stop(),
        setSubject(value) {
            subject = value;
        },
        async advance(milliseconds) {
            t.mock.timers.tick(milliseconds);
            await nextTurn();
        },
        async setVisible(visible) {
            document.visibilityState = visible ? 'visible' : 'hidden';
            document.dispatchEvent(new Event('visibilitychange'));
            await vue.nextTick();
        },
        async setActive(active) {
            for (const callback of active ? activated : deactivated) callback();
            await vue.nextTick();
        },
    };
}

function page(kind, status = 'running', id = 'item') {
    const item =
        kind === 'buildings'
            ? { id, latest_reconstruction: status === null ? null : { status } }
            : { id, status };
    return { items: [item], total: 1 };
}

const processingStatuses = ['waiting_for_upload', 'preparing', 'scheduled', 'running'];
const terminalStatuses = ['cancelling', 'completed', 'failed', 'cancelled', 'crashed'];

for (const kind of ['buildings', 'reconstructions']) {
    for (const status of processingStatuses) {
        test(`${kind}: ${status} polls and stops when processing finishes`, async (t) => {
            const f = await fixture(t, kind);
            const query = f.start();
            const processing = page(kind, status);
            f.requests[0].gate.resolve(processing);
            await nextTurn();
            await f.advance(4_999);
            assert.equal(f.requests.length, 1);
            await f.advance(1);
            assert.equal(f.requests.length, 2);
            assert.deepEqual(query.data.value, processing);
            assert.deepEqual(f.requests[1].options, f.requests[0].options);
            assert.equal(f.requests[1].options.limit, 20);
            assert.equal(f.requests[1].options.sort_order, 'desc');
            await f.advance(20_000);
            assert.equal(f.requests.length, 2, 'Slow polls must not overlap');
            const completed = page(kind, 'completed');
            f.requests[1].gate.resolve(completed);
            await nextTurn();
            await f.advance(20_000);
            assert.equal(f.requests.length, 2);
            assert.deepEqual(query.data.value, completed);
        });
    }

    test(`${kind}: terminal rows and empty pages do not poll`, async (t) => {
        const f = await fixture(t, kind);
        const query = f.start();
        const statuses = kind === 'buildings' ? [...terminalStatuses, null] : terminalStatuses;
        const items = statuses.map((status, index) => page(kind, status, String(index)).items[0]);
        f.requests[0].gate.resolve({ items, total: items.length });
        await nextTurn();
        await f.advance(20_000);
        assert.equal(f.requests.length, 1);
        const refresh = query.refetch();
        f.requests[1].gate.resolve({ items: [], total: 0 });
        await refresh;
        await f.advance(20_000);
        assert.equal(f.requests.length, 2);
    });

    test(`${kind}: initial errors do not start polling`, async (t) => {
        const f = await fixture(t, kind);
        const query = f.start();
        const error = new Error('Unavailable');
        f.requests[0].gate.reject(error);
        await nextTurn();
        assert.equal(query.error.value, error);
        await f.advance(20_000);
        assert.equal(f.requests.length, 1);
    });

    test(`${kind}: initial, automatic, and manual requests use the correct loading state`, async (t) => {
        t.mock.method(console, 'error', () => {});
        const f = await fixture(t, kind);
        const query = f.start();
        const processing = page(kind);
        assert.equal(query.isForegroundLoading.value, true);
        f.requests[0].gate.resolve(processing);
        await nextTurn();
        assert.equal(query.isForegroundLoading.value, false);
        await f.advance(5_000);
        assert.equal(query.isLoading.value, true);
        assert.equal(query.isForegroundLoading.value, false);
        f.requests[1].gate.resolve(processing);
        await nextTurn();

        const refresh = query.refetch(true);
        assert.equal(query.isForegroundLoading.value, true);
        const error = new Error('Manual request failed');
        const failure = assert.rejects(refresh, (caught) => caught === error);
        f.requests[2].gate.reject(error);
        await failure;
        assert.equal(query.isForegroundLoading.value, false);
        assert.deepEqual(query.data.value, processing);

        await f.advance(5_000);
        assert.equal(query.isLoading.value, true);
        assert.equal(query.isForegroundLoading.value, false);
        f.requests[3].gate.resolve(processing);
        await nextTurn();
        assert.equal(query.error.value, null);
        const retry = query.refetch();
        assert.equal(query.isForegroundLoading.value, true);
        f.requests[4].gate.resolve(page(kind, 'completed'));
        await retry;
        assert.equal(query.isForegroundLoading.value, false);
    });

    for (const status of [401, 503, 'network']) {
        test(`${kind}: cached processing rows keep polling after ${status} errors`, async (t) => {
            t.mock.method(console, 'error', () => {});
            const f = await fixture(t, kind);
            const query = f.start();
            const processing = page(kind);
            f.requests[0].gate.resolve(processing);
            await nextTurn();
            await f.advance(5_000);
            const error = Object.assign(new Error('Unavailable'), { status });
            f.requests[1].gate.reject(error);
            await nextTurn();
            assert.equal(query.error.value, error);
            assert.deepEqual(query.data.value, processing);
            await f.advance(5_000);
            assert.equal(f.requests.length, 3);
            f.requests[2].gate.resolve(page(kind, 'completed'));
            await nextTurn();
            assert.equal(query.error.value, null);
        });
    }

    const keyChanges =
        kind === 'buildings'
            ? ['offset', 'reconstructionStatus', 'search']
            : ['offset', 'buildingId'];
    for (const change of keyChanges) {
        test(`${kind}: ${change} changes leave obsolete polls behind`, async (t) => {
            const f = await fixture(t, kind);
            const query = f.start();
            f.requests[0].gate.resolve(page(kind, 'running', 'previous'));
            await nextTurn();
            await f.advance(5_000);
            const value = {
                offset: 20,
                reconstructionStatus: 'running',
                search: '  church  ',
                buildingId: 'building-b',
            }[change];
            f[change].value = value;
            await vue.nextTick();
            assert.equal(f.requests.length, 3);
            assert.equal(query.data.value, undefined);
            assert.equal(query.isForegroundLoading.value, true);
            const expected = change === 'search' ? 'church' : value;
            if (change === 'buildingId') assert.equal(f.requests[2].buildingId, expected);
            else {
                const option = change === 'reconstructionStatus' ? 'reconstruction_status' : change;
                assert.equal(f.requests[2].options[option], expected);
            }
            const current = page(kind, 'running', 'current');
            f.requests[2].gate.resolve(current);
            f.requests[1].gate.resolve(page(kind, 'running', 'previous'));
            await nextTurn();
            assert.deepEqual(query.data.value, current);
            await f.advance(5_000);
            assert.equal(f.requests.length, 4);
            assert.deepEqual(f.requests[3].options, f.requests[2].options);
            assert.equal(f.requests[3].buildingId, f.requests[2].buildingId);
            f.stop();
            f.requests[3].gate.resolve(current);
            await nextTurn();
            await f.advance(20_000);
            assert.equal(f.requests.length, 4);
        });
    }

    for (const change of kind === 'buildings' ? ['offset'] : ['offset', 'buildingId']) {
        test(`${kind}: returning to cached ${change} restarts after an off-page response`, async (t) => {
            const f = await fixture(t, kind);
            const query = f.start();
            const processing = page(kind);
            f.requests[0].gate.resolve(processing);
            await nextTurn();
            await f.advance(5_000);
            const previous = f[change].value;
            f[change].value = change === 'offset' ? 20 : 'building-b';
            await vue.nextTick();
            f.requests[2].gate.resolve(page(kind, 'completed'));
            f.requests[1].gate.resolve(processing);
            await nextTurn();
            f[change].value = previous;
            await vue.nextTick();
            assert.deepEqual(query.data.value, processing);
            assert.equal(f.requests.length, 4, 'Fresh cached processing data must resume polling');
            assert.equal(query.isForegroundLoading.value, false);
            f.requests[3].gate.resolve(processing);
            await nextTurn();
            await f.advance(5_000);
            assert.equal(f.requests.length, 5);
            f.requests[4].gate.resolve(page(kind, 'completed'));
            await nextTurn();
        });
    }

    for (const pause of ['visibility', 'activation']) {
        test(`${kind}: ${pause} pauses and resumes fresh cached processing pages`, async (t) => {
            const f = await fixture(t, kind);
            const query = f.start();
            const processing = page(kind);
            f.requests[0].gate.resolve(processing);
            await nextTurn();
            const setEnabled = pause === 'visibility' ? f.setVisible : f.setActive;
            await setEnabled(false);
            await f.advance(10_000);
            assert.equal(f.requests.length, 1);
            await setEnabled(true);
            assert.equal(f.requests.length, 2);
            assert.equal(query.isForegroundLoading.value, false);
            await setEnabled(false);
            f.requests[1].gate.resolve(processing);
            await nextTurn();
            await f.advance(10_000);
            assert.equal(f.requests.length, 2);
            await setEnabled(true);
            assert.equal(f.requests.length, 3, 'An off-page response must not prevent resuming');
            f.requests[2].gate.resolve(processing);
            await nextTurn();
            await f.advance(5_000);
            assert.equal(f.requests.length, 4);
            f.requests[3].gate.resolve(page(kind, 'completed'));
            await nextTurn();
        });
    }

    test(`${kind}: an account change stops polling the previous account`, async (t) => {
        const f = await fixture(t, kind);
        f.start();
        f.requests[0].gate.resolve(page(kind));
        await nextTurn();
        f.setSubject('user-b');
        await f.advance(10_000);
        assert.equal(f.requests.length, 1);
    });

    test(`${kind}: unauthenticated queries do not fetch or poll`, async (t) => {
        const f = await fixture(t, kind, null);
        f.start();
        await f.advance(10_000);
        assert.equal(f.requests.length, 0);
    });
}

test('reconstructions: an empty building ID disables requests until an ID is supplied', async (t) => {
    const f = await fixture(t, 'reconstructions');
    f.buildingId.value = '';
    f.start();
    await f.advance(10_000);
    assert.equal(f.requests.length, 0);
    f.buildingId.value = 'building-a';
    await vue.nextTick();
    assert.equal(f.requests.length, 1);
    f.requests[0].gate.resolve(page('reconstructions'));
    await nextTurn();
    await f.advance(5_000);
    assert.equal(f.requests.length, 2);
    f.requests[1].gate.resolve(page('reconstructions', 'completed'));
    await nextTurn();
});

test('steps: poll every five seconds after settlement without overlapping slow requests', async (t) => {
    const f = await fixture(t, 'steps');
    const query = f.start();
    await f.advance(20_000);
    assert.equal(f.requests.length, 1);
    f.requests[0].gate.resolve('preparing-input');
    await nextTurn();
    await f.advance(4_999);
    assert.equal(f.requests.length, 1);
    await f.advance(1);
    assert.equal(f.requests.length, 2);
    assert.equal(query.data.value, 'preparing-input');
    await f.advance(20_000);
    assert.equal(f.requests.length, 2);
    f.requests[1].gate.resolve('reconstructing');
    await nextTurn();
    assert.equal(query.data.value, 'reconstructing');
    await f.advance(5_000);
    assert.equal(f.requests.length, 3);
    f.stop();
    f.requests[2].gate.resolve('exporting');
    await nextTurn();
    await f.advance(20_000);
    assert.equal(f.requests.length, 3);
});

for (const change of ['buildingId', 'reconstructionId']) {
    test(`steps: ${change} switches polling to the current reconstruction`, async (t) => {
        const f = await fixture(t, 'steps');
        const query = f.start();
        f.requests[0].gate.resolve('preparing');
        await nextTurn();
        await f.advance(5_000);
        f[change].value = 'next-id';
        await vue.nextTick();
        assert.equal(f.requests.length, 3);
        assert.equal(query.data.value, undefined);
        f.requests[2].gate.resolve('current-step');
        f.requests[1].gate.resolve('obsolete-step');
        await nextTurn();
        assert.equal(query.data.value, 'current-step');
        await f.advance(5_000);
        assert.equal(f.requests.length, 4);
        assert.equal(f.requests[3][change], 'next-id');
        f.requests[3].gate.resolve('current-step');
        await nextTurn();
    });

    test(`steps: an empty ${change} pauses polling until both IDs are available`, async (t) => {
        const f = await fixture(t, 'steps');
        f[change].value = '';
        f.start();
        await f.advance(10_000);
        assert.equal(f.requests.length, 0);
        f[change].value = 'valid-id';
        await vue.nextTick();
        assert.equal(f.requests.length, 1);
        f.requests[0].gate.resolve('preparing');
        await nextTurn();
        f[change].value = '';
        await vue.nextTick();
        await f.advance(10_000);
        assert.equal(f.requests.length, 1);
        f[change].value = 'valid-id';
        await vue.nextTick();
        assert.equal(f.requests.length, 2);
        f.requests[1].gate.resolve('reconstructing');
        await nextTurn();
    });
}

test('steps: an initial error still retries automatically', async (t) => {
    t.mock.method(console, 'error', () => {});
    const f = await fixture(t, 'steps');
    const query = f.start();
    const error = new Error('Unavailable');
    f.requests[0].gate.reject(error);
    await nextTurn();
    assert.equal(query.error.value, error);
    await f.advance(5_000);
    assert.equal(f.requests.length, 2);
    f.requests[1].gate.resolve('reconstructing');
    await nextTurn();
    assert.equal(query.error.value, null);
    assert.equal(query.data.value, 'reconstructing');
});
