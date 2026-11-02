import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
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
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return { cache, mutation, requests, stop: () => scope.stop() };
}

test('cancellation optimistically updates cached pages and applies the returned row', async (t) => {
    const f = await fixture(t);
    const page = { items: [row, sibling], total: 2 };
    const keys = [listKey(), listKey(20)];
    const untouchedKeys = [listKey(0, 'other-building'), listKey(0, 'building-a', 'other-user')];
    for (const key of [...keys, ...untouchedKeys]) f.cache.setQueryData(key, page);

    const promise = f.mutation.mutateAsync(variables);
    await nextTurn();
    for (const key of keys) {
        assert.deepEqual(f.cache.getQueryData(key), {
            ...page,
            items: [{ ...row, status: 'cancelling' }, sibling],
        });
    }
    for (const key of untouchedKeys) assert.equal(f.cache.getQueryData(key), page);
    assert.equal(
        f.requests[0].url,
        '/buildings/building-a/reconstructions/reconstruction-a/cancel',
    );
    assert.equal(f.requests[0].init.method, 'POST');

    // Other rows can change while cancellation is pending.
    const updatedSibling = { ...sibling, progress: 0.8 };
    f.cache.setQueryData(keys[0], {
        ...page,
        items: [f.cache.getQueryData(keys[0]).items[0], updatedSibling],
    });
    const cancelled = { ...row, status: 'cancelled', error_message: 'Cancellation requested' };
    f.requests[0].gate.resolve(cancelled);
    assert.equal(await promise, cancelled);
    assert.deepEqual(f.cache.getQueryData(keys[0]).items, [cancelled, updatedSibling]);
    assert.deepEqual(f.cache.getQueryData(keys[1]).items, [cancelled, sibling]);
});

test('failure rolls back optimistic rows while preserving newer cached data', async (t) => {
    const f = await fixture(t);
    const page = { items: [row, sibling], total: 2 };
    f.cache.setQueryData(listKey(), page);
    f.cache.setQueryData(listKey(20), page);
    const promise = f.mutation.mutateAsync(variables);
    const failure = assert.rejects(promise, { message: 'Cancellation failed' });
    await nextTurn();

    const updatedSibling = { ...sibling, progress: 0.8 };
    f.cache.setQueryData(listKey(), {
        ...page,
        items: [f.cache.getQueryData(listKey()).items[0], updatedSibling],
    });
    const completed = { ...row, status: 'completed', progress: 1 };
    f.cache.setQueryData(listKey(20), { ...page, items: [completed, sibling] });
    f.requests[0].gate.reject(new Error('Cancellation failed'));
    await failure;
    assert.deepEqual(f.cache.getQueryData(listKey()).items, [row, updatedSibling]);
    assert.deepEqual(f.cache.getQueryData(listKey(20)).items, [completed, sibling]);
});

test('an in-flight poll cannot overwrite cancellation, which settles after the view closes', async (t) => {
    const f = await fixture(t);
    const poll = deferred();
    const entry = f.cache.ensure({ key: listKey(), query: () => poll.promise });
    const page = { items: [row], total: 1 };
    f.cache.setQueryData(listKey(), page);
    const polling = f.cache.fetch(entry);
    const promise = f.mutation.mutateAsync(variables);
    await nextTurn();
    poll.resolve(page);
    await polling;
    assert.equal(f.cache.getQueryData(listKey()).items[0].status, 'cancelling');

    f.stop();
    const cancelled = { ...row, status: 'cancelled' };
    f.requests[0].gate.resolve(cancelled);
    await promise;
    assert.equal(f.cache.getQueryData(listKey()).items[0], cancelled);
});
