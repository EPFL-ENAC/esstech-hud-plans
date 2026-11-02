import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
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
        'src/lib/utils/resumableDownload': { downloadResumable() {} },
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
        invalidation,
        query: (options) => app.runWithContext(() => scope.run(() => useQuery(options))),
        stop: () => scope.stop(),
    };
}

for (const status of ['cancelling', 'cancelled']) {
    test(`cancellation applies the backend ${status} row without an optimistic update`, async (t) => {
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
        for (const key of keys) assert.equal(f.cache.getQueryData(key), page);
        assert.equal(
            f.requests[0].url,
            '/buildings/building-a/reconstructions/reconstruction-a/cancel',
        );
        assert.equal(f.requests[0].init.method, 'POST');

        const updatedSibling = { ...sibling, progress: 0.8 };
        f.cache.setQueryData(keys[0], { ...page, items: [row, updatedSibling] });
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
