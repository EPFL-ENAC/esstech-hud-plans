import assert from 'node:assert/strict';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, authFetch = async () => new Response(null, { status: 204 })) {
    const api = await importTypeScript(t, 'src/lib/api.ts', {
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/auth': { authFetch },
    });
    const helpers = await importTypeScript(t, 'src/lib/idempotentRequests.ts', {
        'src/lib/api': api,
    });
    return { ...api, ...helpers };
}

test('idempotent requests preserve request options and headers without mutating them', async (t) => {
    const calls = [];
    const { requestIdempotentJson } = await fixture(t, async (url, init) => {
        calls.push({ url, init });
        return Response.json({ id: 'created' }, { status: 202 });
    });
    const controller = new AbortController();
    for (const headers of [
        { 'Content-Type': 'application/json', 'Idempotency-Key': 'old' },
        [['X-Custom', 'preserved']],
        new Headers({ 'Content-Type': 'application/json', 'Idempotency-Key': 'old' }),
    ]) {
        const before = [...new Headers(headers)];
        const result = await requestIdempotentJson('/submit', {
            idempotencyKey: 'task-id',
            method: 'POST',
            headers,
            body: '{"upload_id":"upload"}',
            signal: controller.signal,
        });
        assert.deepEqual(result, { id: 'created' });
        const { url, init } = calls.at(-1);
        assert.equal(url, 'https://hud.test/submit');
        assert.equal(init.method, 'POST');
        assert.equal(init.body, '{"upload_id":"upload"}');
        assert.equal(init.signal, controller.signal);
        assert.equal(init.headers.get('Idempotency-Key'), 'task-id');
        for (const [key, value] of before) {
            if (key !== 'idempotency-key') assert.equal(init.headers.get(key), value);
        }
        assert.deepEqual([...new Headers(headers)], before);
        assert.equal('idempotencyKey' in init, false);
    }
});

test('an empty replay response resolves to null', async (t) => {
    const { requestIdempotentJson } = await fixture(t);
    assert.equal(await requestIdempotentJson('/submit', { idempotencyKey: 'task-id' }), null);
});

test('one attempt preserves transport and API failures', async (t) => {
    const failure = new TypeError('Network unavailable');
    let attempts = 0;
    const { requestIdempotentJson, ApiError } = await fixture(t, async () => {
        attempts += 1;
        if (attempts === 1) throw failure;
        return Response.json({ detail: { code: 'idempotency_in_progress' } }, { status: 409 });
    });
    await assert.rejects(
        requestIdempotentJson('/submit', { idempotencyKey: 'task-id' }),
        (error) => error === failure,
    );
    assert.equal(attempts, 1);
    await assert.rejects(
        requestIdempotentJson('/submit', { idempotencyKey: 'task-id' }),
        (error) => {
            assert.ok(error instanceof ApiError);
            assert.equal(error.status, 409);
            assert.deepEqual(error.body, { detail: { code: 'idempotency_in_progress' } });
            return true;
        },
    );
    assert.equal(attempts, 2);
});

test('the retry classifier distinguishes transient, authentication, and permanent failures', async (t) => {
    const { ApiError, idempotentRequestFailureAction: classify } = await fixture(t);
    assert.equal(classify(new TypeError('Failed to fetch')), 'retry');
    for (const status of [408, 429, 500, 502, 503, 504]) {
        assert.equal(classify(new ApiError('Transient', status, null)), 'retry');
    }
    for (const status of [401, 403]) {
        assert.equal(classify(new ApiError('Authentication', status, null)), 'blocked');
    }
    for (const status of [400, 404, 409, 422]) {
        assert.equal(classify(new ApiError('Permanent', status, null)), 'failed');
    }
    assert.equal(
        classify(
            new ApiError('Busy', 409, {
                detail: { code: 'idempotency_in_progress' },
            }),
        ),
        'retry',
    );
    for (const body of [
        null,
        'conflict',
        {},
        { detail: null },
        { detail: 'conflict' },
        { detail: { code: 'other_conflict' } },
    ]) {
        assert.equal(classify(new ApiError('Conflict', 409, body)), 'failed');
    }
    for (const error of [
        new Error('Unexpected'),
        new DOMException('Aborted', 'AbortError'),
        null,
    ]) {
        assert.equal(classify(error), 'failed');
    }
});
