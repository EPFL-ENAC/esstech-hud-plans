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
        uploadedVideosQuery(offset, open) {
            return app.runWithContext(() =>
                scope.run(() => queries.useUploadedVideosQuery(offset, open)),
            );
        },
        uploadQuery(uploadId) {
            return app.runWithContext(() => scope.run(() => queries.useUploadQuery(uploadId)));
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

test('getUpload encodes the ID and uses the authenticated detail endpoint', async (t) => {
    const f = await fixture(t);
    const promise = f.uploads.getUpload('video/with spaces');
    assert.equal(f.requests[0].url, 'https://hud.test/api/uploads/video%2Fwith%20spaces');
    const upload = rows('detail')[0];
    respond(f.requests[0], upload);
    assert.deepEqual(await promise, upload);
});

test('upload detail queries follow ID changes without exposing the previous upload', async (t) => {
    const f = await fixture(t);
    const id = ref('first');
    const query = f.uploadQuery(id);
    respond(f.requests[0], rows('first')[0]);
    await nextTurn();
    assert.equal(query.data.value.id, 'first-0');
    id.value = 'second';
    await nextTick();
    assert.equal(query.data.value, undefined);
    assert.equal(f.requests[1].url, 'https://hud.test/api/uploads/second');
    respond(f.requests[1], rows('second')[0]);
    await nextTurn();
    assert.equal(query.data.value.id, 'second-0');
});

test('upload details are cached separately for each account', async (t) => {
    const f = await fixture(t);
    const first = f.uploadQuery(ref('shared-id'));
    respond(f.requests[0], rows('private-a')[0]);
    await nextTurn();
    f.setSubject('user-b');
    const second = f.uploadQuery(ref('shared-id'));
    assert.equal(second.data.value, undefined);
    respond(f.requests[1], { detail: 'Not found' }, 404);
    await nextTurn();
    assert.equal(second.state.value.status, 'error');
    assert.equal(second.data.value, undefined);
    assert.equal(first.data.value.id, 'private-a-0');
});

test('detail refresh errors retain data and retry recovers its status', async (t) => {
    const f = await fixture(t);
    const query = f.uploadQuery(ref('pending'));
    respond(f.requests[0], { ...rows('pending')[0], status: 'pending' });
    await nextTurn();
    const failed = query.refetch();
    respond(f.requests[1], { detail: 'Unavailable' }, 503);
    await failed;
    assert.equal(query.state.value.status, 'error');
    assert.equal(query.data.value.status, 'pending');
    const retry = query.refetch();
    respond(f.requests[2], { ...rows('pending')[0], status: 'uploaded' });
    await retry;
    assert.equal(query.state.value.status, 'success');
    assert.equal(query.data.value.status, 'uploaded');
});

test('unauthenticated or empty-ID detail queries make no request', async (t) => {
    const f = await fixture(t, null);
    f.uploadQuery(ref('private'));
    assert.equal(f.requests.length, 0);
    f.setSubject('user-a');
    f.uploadQuery(ref(''));
    assert.equal(f.requests.length, 0);
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

test('uploaded videos query filters on the server and stays inactive while closed', async (t) => {
    const f = await fixture(t);
    const offset = ref(0);
    const open = ref(false);
    const query = f.uploadedVideosQuery(offset, open);
    await nextTurn();
    assert.equal(f.requests.length, 0);
    open.value = true;
    await nextTick();
    assert.equal(
        f.requests[0].url,
        'https://hud.test/api/uploads?offset=0&limit=21&sort_order=desc&status=uploaded',
    );
    respond(f.requests[0], rows('uploaded', 21));
    await nextTurn();
    assert.equal(query.data.value.length, 21);
    open.value = false;
    offset.value = 20;
    await nextTick();
    assert.equal(f.requests.length, 1);
    open.value = true;
    await nextTick();
    assert.equal(
        f.requests[1].url,
        'https://hud.test/api/uploads?offset=20&limit=21&sort_order=desc&status=uploaded',
    );
    respond(f.requests[1], []);
    await nextTurn();
    assert.deepEqual(query.data.value, []);
});

test('uploaded video queries have separate caches for each account', async (t) => {
    const f = await fixture(t);
    const first = f.uploadedVideosQuery(ref(0), ref(true));
    respond(f.requests[0], rows('first-user'));
    await nextTurn();
    f.setSubject('second-user');
    const second = f.uploadedVideosQuery(ref(0), ref(true));
    assert.equal(second.data.value, undefined);
    respond(f.requests[1], rows('second-user'));
    await nextTurn();
    assert.deepEqual(first.data.value, rows('first-user'));
    assert.deepEqual(second.data.value, rows('second-user'));
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
