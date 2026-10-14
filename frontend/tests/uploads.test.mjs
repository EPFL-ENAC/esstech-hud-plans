import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope, nextTick, ref } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, initialSubject = 'user-a') {
    const requests = [];
    let subject = initialSubject;
    const api = await importTypeScript(t, 'src/lib/api.ts', {
        'boot/api': { baseUrl: 'https://hud.test/api' },
        'src/lib/auth': {
            authFetch(url, init) {
                const gate = deferred();
                requests.push({ url, init, gate });
                return gate.promise;
            },
        },
    });
    const uploads = await importTypeScript(t, 'src/lib/uploads.ts', {
        'src/lib/api': api,
    });
    const queries = await importTypeScript(t, 'src/queries/uploads.ts', {
        vue: import.meta.resolve('vue'),
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/lib/auth': { getAuthSubject: () => subject },
        'src/lib/uploads': uploads,
    });
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, { queryOptions: { gcTime: Infinity } });
    const scope = effectScope();
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return {
        api,
        uploads,
        requests,
        setSubject(value) {
            subject = value;
        },
        query(offset = ref(0)) {
            return app.runWithContext(() => scope.run(() => queries.useMyUploadsQuery(offset)));
        },
    };
}

function respond(request, body, status = 200) {
    request.gate.resolve(new Response(JSON.stringify(body), { status }));
}

function rows(prefix, count = 1) {
    return Array.from({ length: count }, (_, index) => ({
        id: `${prefix}-${index}`,
        filename: `${prefix}-${index}.mp4`,
        status: 'uploaded',
    }));
}

test('listUploads uses the authenticated HTTP boundary with default pagination', async (t) => {
    const f = await fixture(t);
    const promise = f.uploads.listUploads();
    assert.equal(
        f.requests[0].url,
        'https://hud.test/api/uploads?offset=0&limit=100&sort_order=desc',
    );
    const data = rows('default');
    respond(f.requests[0], data);
    assert.deepEqual(await promise, data);
});

test('listUploads preserves explicit offset, limit, and ordering', async (t) => {
    const f = await fixture(t);
    const promise = f.uploads.listUploads({ offset: 40, limit: 21, sort_order: 'asc' });
    assert.equal(
        f.requests[0].url,
        'https://hud.test/api/uploads?offset=40&limit=21&sort_order=asc',
    );
    respond(f.requests[0], []);
    assert.deepEqual(await promise, []);
});

for (const status of [401, 503]) {
    test(`HTTP ${status} retains status and parsed error body`, async (t) => {
        const f = await fixture(t);
        const promise = f.uploads.listUploads();
        respond(f.requests[0], { detail: 'Unavailable' }, status);
        await assert.rejects(promise, (error) => {
            assert.ok(error instanceof f.api.ApiError);
            assert.equal(error.status, status);
            assert.deepEqual(error.body, { detail: 'Unavailable' });
            return true;
        });
    });
}

test('shared requestJson preserves plain text errors and empty success responses', async (t) => {
    const f = await fixture(t);
    const failure = f.api.requestJson('/plain-error');
    f.requests[0].gate.resolve(new Response('unavailable', { status: 503 }));
    await assert.rejects(failure, (error) => error.body === 'unavailable' && error.status === 503);
    const success = f.api.requestJson('/empty');
    f.requests[1].gate.resolve(new Response(null, { status: 204 }));
    assert.equal(await success, null);
});

test('pagination fetches 21 rows per page and reuses cached previous pages', async (t) => {
    const f = await fixture(t);
    const offset = ref(0);
    const query = f.query(offset);
    assert.equal(
        f.requests[0].url,
        'https://hud.test/api/uploads?offset=0&limit=21&sort_order=desc',
    );
    const firstPage = rows('first', 21);
    respond(f.requests[0], firstPage);
    await nextTurn();
    assert.deepEqual(query.data.value, firstPage);

    offset.value = 20;
    await nextTick();
    assert.equal(
        f.requests[1].url,
        'https://hud.test/api/uploads?offset=20&limit=21&sort_order=desc',
    );
    const secondPage = rows('second', 5);
    respond(f.requests[1], secondPage);
    await nextTurn();
    assert.deepEqual(query.data.value, secondPage);

    offset.value = 0;
    await nextTick();
    await nextTurn();
    assert.deepEqual(query.data.value, firstPage);
    assert.equal(f.requests.length, 2);
});

test('Colada caches upload lists separately for each authenticated subject', async (t) => {
    const f = await fixture(t);
    const first = f.query();
    const firstData = rows('private-a');
    respond(f.requests[0], firstData);
    await nextTurn();
    f.setSubject('user-b');
    const second = f.query();
    assert.equal(second.data.value, undefined);
    const secondData = rows('private-b');
    respond(f.requests[1], secondData);
    await nextTurn();
    assert.deepEqual(first.data.value, firstData);
    assert.deepEqual(second.data.value, secondData);

    f.setSubject('user-a');
    const restored = f.query();
    await nextTurn();
    assert.deepEqual(restored.data.value, firstData);
    assert.equal(f.requests.length, 2);
});

test('an unauthenticated query does not start a request', async (t) => {
    const f = await fixture(t, null);
    const query = f.query();
    await nextTurn();
    assert.equal(query.state.value.status, 'pending');
    assert.equal(f.requests.length, 0);
});

test('refresh failures preserve cached rows and retry can recover', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    const original = rows('cached');
    respond(f.requests[0], original);
    await nextTurn();

    const refresh = query.refetch();
    assert.equal(query.isLoading.value, true);
    assert.deepEqual(query.data.value, original);
    respond(f.requests[1], { detail: 'Unavailable' }, 503);
    await refresh;
    assert.equal(query.state.value.status, 'error');
    assert.deepEqual(query.data.value, original);

    const retry = query.refetch();
    const recovered = rows('recovered');
    respond(f.requests[2], recovered);
    await retry;
    assert.equal(query.state.value.status, 'success');
    assert.deepEqual(query.data.value, recovered);
});
