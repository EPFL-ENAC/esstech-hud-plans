import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope, nextTick, ref } from 'vue';
import * as vue from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, initialSubject = 'owner') {
    const requests = [];
    const details = [];
    const visible = ref(true);
    const activated = [];
    const deactivated = [];
    let subject = initialSubject;
    const queries = await importTypeScript(t, 'src/queries/buildings.ts', {
        vue: {
            computed: vue.computed,
            ref: vue.ref,
            watch: vue.watch,
            toValue: vue.toValue,
            onMounted: vue.onMounted,
            onScopeDispose: vue.onScopeDispose,
            onActivated: (callback) => activated.push(callback),
            onDeactivated: (callback) => deactivated.push(callback),
        },
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/composables/useDocumentVisibility': { useDocumentVisibility: () => visible },
        'src/lib/auth': { getAuthSubject: () => subject },
        'src/lib/buildings': {
            isReconstructionProcessing() {
                return false;
            },
            listBuildingLocations() {},
            listBuildings(options) {
                const gate = deferred();
                requests.push({ ...options, gate });
                return gate.promise;
            },
            getBuilding(id) {
                const gate = deferred();
                details.push({ id, gate });
                return gate.promise;
            },
        },
    });
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, {
        queryOptions: { gcTime: Infinity },
        mutationOptions: { gcTime: Infinity },
    });
    const scope = effectScope();
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    const run = (callback) => app.runWithContext(() => scope.run(callback));
    return {
        requests,
        details,
        app,
        run,
        cache: app.runWithContext(useQueryCache),
        query: () => run(queries.useBuildingPickerQuery),
        selected: (id) => run(() => queries.useBuildingQuery(id)),
        setSubject(value) {
            subject = value;
        },
        async setVisible(value) {
            visible.value = value;
            await nextTick();
        },
        async setActive(value) {
            for (const callback of value ? activated : deactivated) callback();
            await nextTick();
        },
    };
}

function buildings(count, offset = 0) {
    return Array.from({ length: count }, (_, index) => ({ id: String(offset + index) }));
}

async function respond(request, items, total) {
    request.gate.resolve({ items, total });
    await nextTurn();
}

for (const count of [0, 1, 20, 21, 40, 41]) {
    test(`the picker loads ${count} buildings one page at a time`, async (t) => {
        const f = await fixture(t);
        const query = f.query();
        assert.equal(f.requests.length, 1);
        assert.equal(f.requests[0].offset, 0);
        assert.equal(f.requests[0].limit, 20);
        assert.equal(f.requests[0].sort_order, 'desc');
        await respond(f.requests[0], buildings(Math.min(20, count)), count);
        assert.equal(f.requests.length, 1, 'Mounting must not fetch subsequent pages');
        for (let offset = 20; offset < count; offset += 20) {
            assert.equal(query.hasNextPage.value, true);
            const request = query.loadNextPage({ cancelRefetch: false });
            assert.equal(f.requests.at(-1).offset, offset);
            await respond(
                f.requests.at(-1),
                buildings(Math.min(20, count - offset), offset),
                count,
            );
            await request;
        }
        assert.equal(query.hasNextPage.value, false);
        const expectedOffsets = Array.from(
            { length: Math.max(1, Math.ceil(count / 20)) },
            (_, i) => i * 20,
        );
        await query.loadNextPage();
        assert.deepEqual(
            f.requests.map(({ offset }) => offset),
            expectedOffsets,
        );
        assert.deepEqual(query.data.value.pageParams, expectedOffsets);
        assert.deepEqual(
            query.data.value.pages.flatMap((page) => page.items),
            buildings(count),
        );
    });
}

test('repeated scroll requests share one pending next page', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    await respond(f.requests[0], buildings(20), 40);
    const first = query.loadNextPage();
    const second = query.loadNextPage();
    assert.equal(f.requests.length, 2);
    await respond(f.requests[1], buildings(20, 20), 40);
    await Promise.all([first, second]);
    assert.equal(query.data.value.pages.length, 2);
});

test('an empty next page stops loading even if the total is outdated', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    await respond(f.requests[0], buildings(20), 100);
    const next = query.loadNextPage();
    await respond(f.requests[1], [], 100);
    await next;
    assert.equal(query.hasNextPage.value, false);
    await query.loadNextPage();
    assert.equal(f.requests.length, 2);
});

test('next-page failures retain choices and retry the same offset', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    await respond(f.requests[0], buildings(20), 40);
    const next = query.loadNextPage();
    f.requests[1].gate.reject(new Error('Unavailable'));
    await next;
    assert.equal(query.state.value.status, 'error');
    assert.deepEqual(query.data.value.pages[0].items, buildings(20));
    const retry = query.loadNextPage();
    assert.equal(f.requests[2].offset, 20);
    await respond(f.requests[2], buildings(20, 20), 40);
    await retry;
    assert.equal(query.state.value.status, 'success');
    assert.equal(query.data.value.pages.length, 2);
});

test('refreshing a shrinking result discards obsolete cached pages', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    await respond(f.requests[0], buildings(20), 40);
    const next = query.loadNextPage();
    await respond(f.requests[1], buildings(20, 20), 40);
    await next;
    const refresh = query.refetch();
    await respond(f.requests[2], buildings(5), 5);
    await refresh;
    assert.equal(query.data.value.pages.length, 1);
    assert.equal(query.hasNextPage.value, false);
    assert.equal(f.requests.length, 3);
});

test('reopening the picker reuses fresh loaded pages', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    await respond(f.requests[0], buildings(20), 40);
    const next = query.loadNextPage();
    await respond(f.requests[1], buildings(20, 20), 40);
    await next;
    const reopened = f.query();
    await nextTurn();
    assert.equal(f.requests.length, 2);
    assert.deepEqual(reopened.data.value, query.data.value);
});

for (const pause of ['visibility', 'activation']) {
    test(`the picker pauses requests with ${pause}`, async (t) => {
        const f = await fixture(t);
        const query = f.query();
        await respond(f.requests[0], buildings(20), 40);
        const setEnabled = pause === 'visibility' ? f.setVisible : f.setActive;
        await setEnabled(false);
        await query.loadNextPage();
        assert.equal(f.requests.length, 1);
        await setEnabled(true);
        const next = query.loadNextPage();
        await respond(f.requests[1], buildings(20, 20), 40);
        await next;
    });
}

test('picker caches are scoped to the account and old instances stop loading', async (t) => {
    const f = await fixture(t);
    const first = f.query();
    await respond(f.requests[0], buildings(20), 40);
    f.setSubject('another-owner');
    await first.loadNextPage();
    assert.equal(f.requests.length, 1);
    const second = f.query();
    assert.equal(second.data.value, undefined);
    await respond(f.requests[1], [{ id: 'private' }], 1);
    assert.equal(first.data.value.pages[0].items.length, 20);
    assert.deepEqual(second.data.value.pages[0].items, [{ id: 'private' }]);
});

test('an unauthenticated picker makes no request', async (t) => {
    const f = await fixture(t, null);
    const query = f.query();
    await query.loadNextPage();
    assert.equal(f.requests.length, 0);
});

test('a selected building resolves independently of loaded picker pages', async (t) => {
    const f = await fixture(t);
    f.query();
    await respond(f.requests[0], buildings(20), 500);
    const id = ref('499');
    const selected = f.selected(id);
    assert.equal(f.details[0].id, '499');
    f.details[0].gate.resolve({ id: '499', name: 'Last building' });
    await nextTurn();
    assert.equal(selected.data.value.name, 'Last building');
    assert.equal(f.requests.length, 1);
    id.value = 'missing';
    await nextTick();
    assert.equal(selected.data.value, undefined);
    const failure = Object.assign(new Error('Not found'), { status: 404 });
    f.details[1].gate.reject(failure);
    await nextTurn();
    assert.equal(selected.state.value.status, 'error');
});

test('saving building details invalidates the picker cache', async (t) => {
    const f = await fixture(t);
    const invalidation = t.mock.method(f.cache, 'invalidateQueries', () => Promise.resolve());
    const building = { id: 'saved', name: 'Updated' };
    const { useUpdateBuildingMutation } = await importTypeScript(t, 'src/mutations/buildings.ts', {
        vue: import.meta.resolve('vue'),
        'vue-i18n': { useI18n: () => ({ t: (key) => key }) },
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/lib/auth': { getAuthSubject: () => 'owner' },
        'src/lib/buildings': {
            ApiError: class extends Error {},
            updateBuilding: async () => building,
        },
    });
    await f.run(useUpdateBuildingMutation).mutateAsync({ buildingId: 'saved', details: {} });
    assert.deepEqual(
        invalidation.mock.calls.map((call) => call.arguments[0]),
        [
            { key: ['buildings', 'owner', 'picker'] },
            { key: ['buildings', 'owner', 'list'] },
            { key: ['buildings', 'owner', 'locations'] },
        ],
    );
});
