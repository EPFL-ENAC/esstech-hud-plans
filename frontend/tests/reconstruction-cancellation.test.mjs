import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { computed, createApp, effectScope, ref, watch } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQuery, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

const variables = { buildingId: 'building-a', reconstructionId: 'reconstruction-a' };
const row = { id: variables.reconstructionId, status: 'running', progress: 0.4 };
const sibling = { id: 'reconstruction-b', status: 'running', progress: 0.2 };
const listKey = (offset = 0, buildingId = 'building-a', subject = 'test-user') => [
    'buildings',
    subject,
    'detail',
    buildingId,
    'reconstructions',
    'list',
    { offset },
];

async function fixture(t) {
    const requests = [];
    const listRequests = [];
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/api': {
            ApiError: class extends Error {},
            requestJson(url, init) {
                const gate = deferred();
                requests.push({ url, init, gate });
                return gate.promise;
            },
        },
        'src/lib/downloads/resumableDownload': { ResumableDownload: class {} },
    });
    const { useCancelReconstructionMutation } = await importTypeScript(
        t,
        'src/mutations/reconstructions.ts',
        {
            vue: import.meta.resolve('vue'),
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'src/lib/auth': { getAuthSubject: () => 'test-user' },
            'src/lib/buildings': buildings,
        },
    );
    const { useReconstructionsQuery } = await importTypeScript(
        t,
        'src/queries/reconstructions.ts',
        {
            vue: { computed, ref, watch, onActivated() {}, onDeactivated() {} },
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'src/lib/auth': { getAuthSubject: () => 'test-user' },
            'src/composables/useDocumentVisibility': { useDocumentVisibility: () => ref(true) },
            'src/lib/buildings': {
                ...buildings,
                listReconstructions(buildingId, options) {
                    const gate = deferred();
                    listRequests.push({ buildingId, options, gate });
                    return gate.promise;
                },
            },
            'src/queries/downloadProgress': { trackDownloadProgress() {} },
        },
    );
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, {
        queryOptions: { gcTime: Infinity },
        mutationOptions: { gcTime: Infinity },
    });
    const scope = effectScope();
    const cache = app.runWithContext(() => useQueryCache());
    const mutation = app.runWithContext(() => scope.run(useCancelReconstructionMutation));
    const invalidation = t.mock.method(cache, 'invalidateQueries');
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        cache,
        mutation,
        requests,
        listRequests,
        invalidation,
        query: (options) => app.runWithContext(() => scope.run(() => useQuery(options))),
        reconstructions: () =>
            app.runWithContext(() =>
                scope.run(() => useReconstructionsQuery(ref('building-a'), ref(0))),
            ),
        stop: () => scope.stop(),
    };
}

for (const status of ['cancelling', 'cancelled']) {
    test(`cancellation is optimistic across cached pages and applies the backend ${status} row`, async (t) => {
        const f = await fixture(t);
        const page = { items: [row, sibling], total: 2 };
        const keys = [listKey(), listKey(20)];
        const untouchedKeys = [
            listKey(0, 'other-building'),
            listKey(0, 'building-a', 'other-user'),
        ];
        for (const key of [...keys, ...untouchedKeys]) f.cache.setQueryData(key, page);

        const promise = f.mutation.mutateAsync(variables);
        await nextTurn();
        assert.equal(f.mutation.isLoading.value, true);
        for (const key of keys) {
            assert.deepEqual(f.cache.getQueryData(key), {
                ...page,
                items: [{ ...row, status: 'cancelling' }, sibling],
            });
        }
        assert.equal(
            f.requests[0].url,
            '/buildings/building-a/reconstructions/reconstruction-a/cancel',
        );
        assert.equal(f.requests[0].init.method, 'POST');

        const updatedSibling = { ...sibling, progress: 0.8 };
        f.cache.setQueryData(keys[0], {
            ...page,
            items: [f.cache.getQueryData(keys[0]).items[0], updatedSibling],
        });
        const result = { ...row, status, error_message: 'Cancellation requested' };
        f.requests[0].gate.resolve(result);
        assert.equal(await promise, result);
        assert.equal(f.mutation.isLoading.value, false);
        assert.deepEqual(f.cache.getQueryData(keys[0]).items, [result, updatedSibling]);
        assert.deepEqual(f.cache.getQueryData(keys[1]).items, [result, sibling]);
        for (const key of untouchedKeys) assert.equal(f.cache.getQueryData(key), page);
        assert.equal(f.invalidation.mock.callCount(), 3);
    });
}

test('failed requests refresh the persisted cancelling row and allow retries', async (t) => {
    const f = await fixture(t);
    let serverRow = row;
    const query = f.query({
        key: listKey(),
        query: async () => ({ items: [serverRow], total: 1 }),
        staleTime: 30_000,
    });
    await nextTurn();
    assert.equal(query.data.value.items[0], row);
    const promise = f.mutation.mutateAsync(variables);
    const failure = assert.rejects(promise, { message: 'Cancellation failed' });
    await nextTurn();
    const cancelling = { ...row, status: 'cancelling' };
    serverRow = cancelling;
    f.requests[0].gate.reject(new Error('Cancellation failed'));
    await failure;
    await nextTurn();
    assert.equal(query.data.value.items[0], cancelling);
    assert.equal(f.invalidation.mock.callCount(), 3);

    const retry = f.mutation.mutateAsync(variables);
    await nextTurn();
    const cancelled = { ...row, status: 'cancelled' };
    serverRow = cancelled;
    f.requests[1].gate.resolve(cancelled);
    await retry;
    assert.equal(f.cache.getQueryData(listKey()).items[0], cancelled);
});

test('a successful response cancels an older poll and updates the cache after the view closes', async (t) => {
    const f = await fixture(t);
    const poll = deferred();
    const entry = f.cache.ensure({ key: listKey(), query: () => poll.promise });
    const page = { items: [row], total: 1 };
    f.cache.setQueryData(listKey(), page);
    const promise = f.mutation.mutateAsync(variables);
    await nextTurn();
    const polling = f.cache.fetch(entry);
    f.stop();
    const cancelling = { ...row, status: 'cancelling' };
    f.requests[0].gate.resolve(cancelling);
    await promise;
    poll.resolve(page);
    await polling;
    assert.equal(f.cache.getQueryData(listKey()).items[0], cancelling);
});

test('refetches use server data during cancellation and the mutation applies its response', async (t) => {
    const f = await fixture(t);
    const query = f.reconstructions();
    f.listRequests[0].gate.resolve({ items: [row, sibling], total: 2 });
    await nextTurn();
    const promise = f.mutation.mutateAsync(variables);
    await nextTurn();
    assert.equal(query.data.value.items[0].status, 'cancelling');

    const refresh = query.refetch();
    const updatedSibling = { ...sibling, progress: 0.8 };
    f.listRequests[1].gate.resolve({ items: [row, updatedSibling], total: 2 });
    await refresh;
    assert.equal(query.data.value.items[0], row);
    assert.equal(query.data.value.items[1], updatedSibling);

    const cancelling = { ...row, status: 'cancelling' };
    f.requests[0].gate.resolve(cancelling);
    await promise;
    assert.deepEqual(query.data.value.items, [cancelling, updatedSibling]);
    f.listRequests[2].gate.resolve({ items: [cancelling, updatedSibling], total: 2 });
    await nextTurn();
});

for (const status of ['cancelling', 'cancelled', 'completed', 'failed', 'crashed']) {
    test(`a server-confirmed ${status} row is preserved when the cancel request fails`, async (t) => {
        const f = await fixture(t);
        const query = f.reconstructions();
        f.listRequests[0].gate.resolve({ items: [row], total: 1 });
        await nextTurn();
        const promise = f.mutation.mutateAsync(variables);
        const failure = assert.rejects(promise, { message: 'Response lost' });
        await nextTurn();
        const refresh = query.refetch();
        const confirmed = { ...row, status };
        f.listRequests[1].gate.resolve({ items: [confirmed], total: 1 });
        await refresh;
        assert.equal(query.data.value.items[0], confirmed);

        f.requests[0].gate.reject(new Error('Response lost'));
        await failure;
        assert.equal(query.data.value.items[0], confirmed);
        f.listRequests[2].gate.resolve({ items: [confirmed], total: 1 });
        await nextTurn();
    });
}

test('a delayed cancelling response does not replace a server-confirmed cancelled row', async (t) => {
    const f = await fixture(t);
    const query = f.reconstructions();
    f.listRequests[0].gate.resolve({ items: [row], total: 1 });
    await nextTurn();
    const promise = f.mutation.mutateAsync(variables);
    await nextTurn();
    const refresh = query.refetch();
    const cancelled = { ...row, status: 'cancelled' };
    f.listRequests[1].gate.resolve({ items: [cancelled], total: 1 });
    await refresh;
    f.requests[0].gate.resolve({ ...row, status: 'cancelling' });
    await promise;
    assert.equal(query.data.value.items[0], cancelled);
    f.listRequests[2].gate.resolve({ items: [cancelled], total: 1 });
    await nextTurn();
});

test('retrying a persisted cancellation leaves it unchanged if the retry fails', async (t) => {
    const f = await fixture(t);
    const cancelling = { ...row, status: 'cancelling' };
    const page = { items: [cancelling], total: 1 };
    f.cache.setQueryData(listKey(), page);
    const promise = f.mutation.mutateAsync(variables);
    const failure = assert.rejects(promise, { message: 'Still unavailable' });
    await nextTurn();
    assert.equal(f.cache.getQueryData(listKey()).items[0], cancelling);
    f.requests[0].gate.reject(new Error('Still unavailable'));
    await failure;
    assert.equal(f.cache.getQueryData(listKey()).items[0], cancelling);
});
