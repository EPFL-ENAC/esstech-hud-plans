import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope, nextTick, ref } from 'vue';
import * as vue from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada } from '@pinia/colada';
import { PiniaColadaAutoRefetch } from '@pinia/colada-plugin-auto-refetch';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, initialSubject = 'user-a') {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: Date.now() });
    const previousDocument = globalThis.document;
    const document = new EventTarget();
    document.visibilityState = 'visible';
    globalThis.document = document;
    const activated = [];
    const deactivated = [];
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
    const visibility = await importTypeScript(t, 'src/composables/useDocumentVisibility.ts', {
        vue: import.meta.resolve('vue'),
    });
    const queries = await importTypeScript(t, 'src/queries/uploads.ts', {
        vue: {
            computed: vue.computed,
            ref: vue.ref,
            watch: vue.watch,
            onActivated: (callback) => activated.push(callback),
            onDeactivated: (callback) => deactivated.push(callback),
        },
        '@pinia/colada': import.meta.resolve('@pinia/colada'),
        'src/composables/useDocumentVisibility': visibility,
        'src/lib/api': api,
        'src/lib/auth': { getAuthSubject: () => subject },
        'src/lib/uploads': uploads,
    });
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, {
        plugins: [PiniaColadaAutoRefetch()],
        queryOptions: { gcTime: Infinity },
    });
    const scope = effectScope();
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
        if (previousDocument === undefined) delete globalThis.document;
        else globalThis.document = previousDocument;
    });
    return {
        api,
        uploads,
        requests,
        stop: () => scope.stop(),
        async advance(milliseconds) {
            t.mock.timers.tick(milliseconds);
            await nextTurn();
        },
        async setVisible(visible) {
            document.visibilityState = visible ? 'visible' : 'hidden';
            document.dispatchEvent(new Event('visibilitychange'));
            await nextTick();
        },
        async setActive(active) {
            for (const callback of active ? activated : deactivated) callback();
            await nextTick();
        },
        setSubject(value) {
            subject = value;
        },
        query(offset = ref(0)) {
            return app.runWithContext(() => scope.run(() => queries.useMyUploadsQuery(offset)));
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
        size_bytes: 100,
        uploaded_bytes: 100,
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

for (const terminalStatus of ['uploaded', 'failed']) {
    test(`pending upload polls progress and stops at ${terminalStatus}`, async (t) => {
        const f = await fixture(t);
        const query = f.uploadQuery(ref('progress'));
        const pending = { ...rows('progress')[0], status: 'pending', uploaded_bytes: 10 };
        respond(f.requests[0], pending);
        await nextTurn();
        await f.advance(4_999);
        assert.equal(f.requests.length, 1);
        await f.advance(1);
        assert.equal(f.requests.length, 2);
        assert.equal(query.data.value.uploaded_bytes, 10);
        await f.advance(20_000);
        assert.equal(f.requests.length, 2, 'A slow request must not overlap another poll');
        respond(f.requests[1], { ...pending, uploaded_bytes: 60 });
        await nextTurn();
        assert.equal(query.data.value.uploaded_bytes, 60);
        await f.advance(5_000);
        respond(f.requests[2], { ...pending, status: terminalStatus, uploaded_bytes: 100 });
        await nextTurn();
        await f.advance(20_000);
        assert.equal(f.requests.length, 3);
        assert.equal(query.data.value.status, terminalStatus);
    });
}

for (const failure of ['network', 503]) {
    test(`pending upload recovers automatically after ${failure}`, async (t) => {
        const errors = [];
        t.mock.method(console, 'error', (error) => errors.push(error));
        const f = await fixture(t);
        const query = f.uploadQuery(ref('recover'));
        const pending = { ...rows('recover')[0], status: 'pending', uploaded_bytes: 25 };
        respond(f.requests[0], pending);
        await nextTurn();
        await f.advance(5_000);
        if (failure === 'network') f.requests[1].gate.reject(new TypeError('Network unavailable'));
        else respond(f.requests[1], { detail: 'Unavailable' }, failure);
        await nextTurn();
        assert.equal(query.state.value.status, 'error');
        assert.equal(errors.length, 1);
        assert.equal(query.data.value.uploaded_bytes, 25);
        await f.advance(5_000);
        assert.equal(f.requests.length, 3);
        respond(f.requests[2], { ...pending, uploaded_bytes: 75 });
        await nextTurn();
        assert.equal(query.state.value.status, 'success');
        assert.equal(query.data.value.uploaded_bytes, 75);
    });
}

for (const status of [401, 403, 404, 422]) {
    test(`HTTP ${status} stops automatic polling and leaves manual retry available`, async (t) => {
        const errors = [];
        t.mock.method(console, 'error', (error) => errors.push(error));
        const f = await fixture(t);
        const query = f.uploadQuery(ref('unavailable'));
        const pending = { ...rows('unavailable')[0], status: 'pending' };
        respond(f.requests[0], pending);
        await nextTurn();
        await f.advance(5_000);
        respond(f.requests[1], { detail: 'Unavailable' }, status);
        await nextTurn();
        await f.advance(20_000);
        assert.equal(f.requests.length, 2);
        assert.equal(errors.length, 1);
        const retry = query.refetch();
        respond(f.requests[2], { ...pending, status: 'uploaded' });
        await retry;
        assert.equal(query.data.value.status, 'uploaded');
    });
}

test('initial failures and completed upload lists do not opt into polling', async (t) => {
    const f = await fixture(t);
    const query = f.uploadQuery(ref('initial-failure'));
    respond(f.requests[0], { detail: 'Unavailable' }, 503);
    await nextTurn();
    f.query();
    respond(f.requests[1], rows('list'));
    await nextTurn();
    await f.advance(20_000);
    assert.equal(f.requests.length, 2);
    assert.equal(query.state.value.status, 'error');
});

for (const pause of ['visibility', 'activation']) {
    test(`polling pauses and resumes with ${pause}`, async (t) => {
        const f = await fixture(t);
        const query = f.uploadQuery(ref('lifecycle'));
        const pending = { ...rows('lifecycle')[0], status: 'pending' };
        respond(f.requests[0], pending);
        await nextTurn();
        const setEnabled = pause === 'visibility' ? f.setVisible : f.setActive;
        await setEnabled(false);
        await f.advance(10_000);
        assert.equal(f.requests.length, 1);
        await setEnabled(true);
        assert.equal(f.requests.length, 2);
        respond(f.requests[1], { ...pending, uploaded_bytes: 50 });
        await nextTurn();
        await f.advance(5_000);
        assert.equal(f.requests.length, 3);
        respond(f.requests[2], { ...pending, status: 'uploaded' });
        await nextTurn();
        assert.equal(query.data.value.status, 'uploaded');
    });
}

test('ID changes and scope disposal stop polling the previous upload', async (t) => {
    const f = await fixture(t);
    const id = ref('previous');
    const query = f.uploadQuery(id);
    respond(f.requests[0], { ...rows('previous')[0], status: 'pending' });
    await nextTurn();
    id.value = 'next';
    await nextTick();
    assert.equal(query.data.value, undefined);
    respond(f.requests[1], { ...rows('next')[0], status: 'pending' });
    await nextTurn();
    await f.advance(5_000);
    assert.equal(f.requests.length, 3);
    assert.equal(f.requests[2].url, 'https://hud.test/api/uploads/next');
    f.stop();
    respond(f.requests[2], { ...rows('next')[0], status: 'pending' });
    await nextTurn();
    await f.advance(20_000);
    assert.equal(f.requests.length, 3);
});

test('an account change stops the previous account from polling', async (t) => {
    const f = await fixture(t);
    f.uploadQuery(ref('private'));
    respond(f.requests[0], { ...rows('private')[0], status: 'pending' });
    await nextTurn();
    f.setSubject('user-b');
    await f.advance(10_000);
    assert.equal(f.requests.length, 1);
});

test('upload lists poll once per page and stop when visible pending uploads finish', async (t) => {
    const f = await fixture(t);
    const query = f.query();
    const page = rows('page', 21);
    page[0] = { ...page[0], status: 'pending', uploaded_bytes: 10 };
    page[20] = { ...page[20], status: 'pending', uploaded_bytes: 0 };
    respond(f.requests[0], page);
    await nextTurn();
    await f.advance(4_999);
    assert.equal(f.requests.length, 1);
    await f.advance(1);
    assert.equal(f.requests.length, 2);
    assert.equal(
        f.requests[1].url,
        'https://hud.test/api/uploads?offset=0&limit=21&sort_order=desc',
    );
    await f.advance(10_000);
    assert.equal(f.requests.length, 2, 'Slow polls must not overlap');
    page[0] = { ...page[0], uploaded_bytes: 60 };
    respond(f.requests[1], page);
    await nextTurn();
    assert.equal(query.data.value[0].uploaded_bytes, 60);
    await f.advance(5_000);
    page[0] = { ...page[0], status: 'uploaded', uploaded_bytes: 100 };
    respond(f.requests[2], page);
    await nextTurn();
    await f.advance(20_000);
    assert.equal(f.requests.length, 3, 'The extra pagination row must not keep polling alive');
});

test('upload list polling follows pagination and scope disposal', async (t) => {
    const f = await fixture(t);
    const offset = ref(0);
    const query = f.query(offset);
    respond(f.requests[0], [{ ...rows('first')[0], status: 'pending' }]);
    await nextTurn();
    await f.advance(5_000);
    offset.value = 20;
    await nextTick();
    assert.equal(f.requests.length, 3);
    assert.equal(new URL(f.requests[2].url).searchParams.get('offset'), '20');
    respond(f.requests[2], [{ ...rows('second')[0], status: 'pending' }]);
    respond(f.requests[1], rows('first'));
    await nextTurn();
    assert.equal(query.data.value[0].id, 'second-0');
    await f.advance(5_000);
    assert.equal(f.requests.length, 4);
    assert.equal(new URL(f.requests[3].url).searchParams.get('offset'), '20');
    f.stop();
    respond(f.requests[3], [{ ...rows('second')[0], status: 'pending' }]);
    await nextTurn();
    await f.advance(10_000);
    assert.equal(f.requests.length, 4);
});

for (const pause of ['visibility', 'activation']) {
    test(`upload list polling pauses and resumes with ${pause}`, async (t) => {
        const f = await fixture(t);
        f.query();
        const pending = [{ ...rows('list')[0], status: 'pending' }];
        respond(f.requests[0], pending);
        await nextTurn();
        const setEnabled = pause === 'visibility' ? f.setVisible : f.setActive;
        await setEnabled(false);
        await f.advance(10_000);
        assert.equal(f.requests.length, 1);
        await setEnabled(true);
        assert.equal(f.requests.length, 2);
        respond(f.requests[1], pending);
        await nextTurn();
        await f.advance(5_000);
        assert.equal(f.requests.length, 3);
        respond(f.requests[2], rows('list'));
    });
}

for (const status of [401, 403, 404, 422, 503]) {
    test(`upload list polling handles HTTP ${status}`, async (t) => {
        t.mock.method(console, 'error', () => {});
        const f = await fixture(t);
        const query = f.query();
        const pending = [{ ...rows('list')[0], status: 'pending', uploaded_bytes: 25 }];
        respond(f.requests[0], pending);
        await nextTurn();
        await f.advance(5_000);
        respond(f.requests[1], { detail: 'Unavailable' }, status);
        await nextTurn();
        assert.equal(query.data.value[0].uploaded_bytes, 25);
        await f.advance(5_000);
        if (status === 503) {
            assert.equal(f.requests.length, 3);
            respond(f.requests[2], rows('list'));
            await nextTurn();
            assert.equal(query.state.value.status, 'success');
        } else {
            assert.equal(f.requests.length, 2);
        }
    });
}

test('an account change stops upload list polling', async (t) => {
    const f = await fixture(t);
    f.query();
    respond(f.requests[0], [{ ...rows('private')[0], status: 'pending' }]);
    await nextTurn();
    f.setSubject('user-b');
    await f.advance(10_000);
    assert.equal(f.requests.length, 1);
});

test('returning to a pending cached page restarts polling after an off-page response', async (t) => {
    const f = await fixture(t);
    const offset = ref(0);
    const query = f.query(offset);
    const pending = [{ ...rows('first')[0], status: 'pending', uploaded_bytes: 25 }];
    respond(f.requests[0], pending);
    await nextTurn();
    await f.advance(5_000);
    offset.value = 20;
    await nextTick();
    respond(f.requests[2], rows('second'));
    respond(f.requests[1], pending);
    await nextTurn();
    offset.value = 0;
    await nextTick();
    assert.equal(query.data.value[0].uploaded_bytes, 25);
    assert.equal(f.requests.length, 4);
    respond(f.requests[3], pending);
    await nextTurn();
    await f.advance(5_000);
    assert.equal(f.requests.length, 5);
    respond(f.requests[4], rows('first'));
});
