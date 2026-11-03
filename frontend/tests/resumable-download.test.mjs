import assert from 'node:assert/strict';
import { getEventListeners } from 'node:events';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { BLOCK_BYTES, DOWNLOAD_URL, downloadFixture } from './helpers/downloads.mjs';

function response(bytes, headers = {}) {
    return new Response(bytes, { headers: { etag: '"v1"', ...headers } });
}

for (const persistent of [false, true]) {
    for (const stage of ['headers', 'first chunk', 'after one chunk']) {
        test(`60-second timeout: ${stage}, persistent=${persistent}`, async (t) => {
            t.mock.timers.enable({ apis: ['setTimeout'] });
            const f = await downloadFixture(t, { persistent });
            const progress = [];
            const parent = new AbortController();
            f.setFetch(() =>
                stage === 'headers'
                    ? new Promise(() => {})
                    : response(
                          new ReadableStream({
                              start(controller) {
                                  if (stage === 'after one chunk')
                                      controller.enqueue(new Uint8Array([1, 2, 3]));
                              },
                          }),
                      ),
            );
            const download = await f.open();
            const promise = download.download({
                signal: parent.signal,
                onProgress: (value) => progress.push(value),
            });
            const rejection = assert.rejects(promise, { name: 'TimeoutError' });
            await nextTurn();
            t.mock.timers.tick(59_999);
            await nextTurn();
            assert.equal(f.requests[0].signal.aborted, false);
            t.mock.timers.tick(1);
            await rejection;
            assert.equal(parent.signal.aborted, false);
            assert.equal(f.requests[0].signal.aborted, true);
            assert.equal(getEventListeners(parent.signal, 'abort').length, 0);
            assert.equal(download.downloadedBytes, stage === 'after one chunk' ? 3 : 0);
            const events = progress.length;
            t.mock.timers.tick(120_000);
            await nextTurn();
            assert.equal(progress.length, events);

            f.setFetch(() =>
                stage === 'after one chunk'
                    ? new Response(new Uint8Array([4, 5, 6]), {
                          status: 206,
                          headers: { etag: '"v1"', 'content-range': 'bytes 3-5/6' },
                      })
                    : response(new Uint8Array([1, 2, 3, 4, 5, 6])),
            );
            const blob = await download.download();
            assert.deepEqual(
                new Uint8Array(await blob.arrayBuffer()),
                new Uint8Array([1, 2, 3, 4, 5, 6]),
            );
            assert.equal(
                f.requests[1].headers.get('range'),
                stage === 'after one chunk' ? 'bytes=3-' : null,
            );
        });
    }

    test(`continuous progress can take more than 60 seconds, persistent=${persistent}`, async (t) => {
        t.mock.timers.enable({ apis: ['setTimeout'] });
        const f = await downloadFixture(t, { persistent });
        let stream;
        f.setFetch(() =>
            response(
                new ReadableStream({
                    start(controller) {
                        stream = controller;
                    },
                }),
            ),
        );
        const download = await f.open();
        const promise = download.download();
        await nextTurn();
        for (const byte of [1, 2, 3]) {
            t.mock.timers.tick(59_000);
            stream.enqueue(new Uint8Array([byte]));
            await nextTurn();
        }
        stream.close();
        assert.equal((await promise).size, 3);
        t.mock.timers.tick(120_000);
        assert.equal((await download.download()).size, 3);
        assert.equal(f.requests.length, 1);
    });

    test(`large chunks cross commit boundaries without losing bytes, persistent=${persistent}`, async (t) => {
        const f = await downloadFixture(t, { persistent });
        const bytes = new Uint8Array(BLOCK_BYTES * 2 + 19).fill(37);
        f.setFetch(() =>
            response(
                new ReadableStream({
                    start(controller) {
                        controller.enqueue(bytes.subarray(0, BLOCK_BYTES + 7));
                        controller.enqueue(bytes.subarray(BLOCK_BYTES + 7));
                        controller.close();
                    },
                }),
                { 'content-length': String(bytes.length) },
            ),
        );
        const download = await f.open();
        const blob = await download.download();
        assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes);
        assert.equal(download.downloadedBytes, bytes.length);
        assert.equal(f.records.size, 0);
        assert.equal(f.files.size, 0);
        if (persistent) {
            const commits = f.events.filter(([type]) => type === 'commit').map(([, size]) => size);
            assert.deepEqual(commits, [BLOCK_BYTES, BLOCK_BYTES * 2, bytes.length]);
            assert.ok(
                f.events.findIndex(([type]) => type === 'materialize') <
                    f.events.findIndex(([type]) => type === 'remove'),
            );
        }
        await download.reset();
        assert.equal(download.downloadedBytes, 0);
        assert.equal(download.metadata, null);
        assert.equal((await download.download()).size, bytes.length);
    });
}

test('reload resumes from the checkpoint and truncates an uncommitted file tail', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    await f.seed({ bytes: [1, 2, 3, 99, 99], offset: 3, total: 6 });
    f.setFetch(
        () =>
            new Response(new Uint8Array([4, 5, 6]), {
                status: 206,
                headers: { etag: '"v1"', 'content-range': 'bytes 3-5/6' },
            }),
    );
    const download = await f.open();
    assert.equal(download.downloadedBytes, 3);
    const blob = await download.download();
    assert.equal(f.requests[0].headers.get('range'), 'bytes=3-');
    assert.equal(f.requests[0].headers.get('if-range'), '"v1"');
    assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), new Uint8Array([1, 2, 3, 4, 5, 6]));
});

for (const status of [200, 416]) {
    test(`HTTP ${status} replaces saved bytes with a fresh file`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        await f.seed({ bytes: [9, 9, 9], total: 6 });
        f.setFetch(() =>
            status === 416 && f.requests.length === 1
                ? new Response(null, { status: 416 })
                : response(new Uint8Array([1, 2]), { etag: '"v2"', 'content-length': '2' }),
        );
        const download = await f.open();
        assert.deepEqual(
            new Uint8Array(await (await download.download()).arrayBuffer()),
            new Uint8Array([1, 2]),
        );
        if (status === 416) assert.equal(f.requests[1].headers.has('range'), false);
    });
}

for (const headers of [
    { 'content-range': 'bytes 2-5/6', etag: '"v1"' },
    { 'content-range': 'bytes 3-5/6', etag: '"v2"' },
    { 'content-range': 'bytes 3-6/7', etag: '"v1"' },
    { 'content-range': 'invalid', etag: '"v1"' },
]) {
    test(`invalid resumed response is rejected: ${JSON.stringify(headers)}`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        await f.seed({ bytes: [1, 2, 3], total: 6 });
        f.setFetch(() => new Response(new Uint8Array([4, 5, 6]), { status: 206, headers }));
        const download = await f.open();
        await assert.rejects(download.download());
        assert.equal(download.downloadedBytes, 3);
        assert.equal(f.records.get(DOWNLOAD_URL).offset, 3);
    });
}

test('an incomplete full response retains a checkpoint for a later retry', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    f.setFetch(() => response(new Uint8Array([1, 2, 3]), { 'content-length': '6' }));
    const download = await f.open();
    await assert.rejects(download.download(), /Incomplete download/);
    assert.equal(f.records.get(DOWNLOAD_URL).offset, 3);
    assert.equal(f.files.size, 1);
});

test('a missing validator restarts instead of combining unverifiable bytes', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    await f.seed({ bytes: [9, 9], total: 3, etag: '' });
    f.setFetch(() => response(new Uint8Array([1, 2, 3])));
    const download = await f.open();
    assert.equal((await download.download()).size, 3);
    assert.equal(f.requests[0].headers.has('range'), false);
});

test('cancellation during a file commit lets its checkpoint finish and suppresses progress', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    f.setFetch(() =>
        response(
            new ReadableStream({
                start(controller) {
                    controller.enqueue(new Uint8Array(BLOCK_BYTES).fill(1));
                },
            }),
            { 'content-length': String(BLOCK_BYTES + 1) },
        ),
    );
    const download = await f.open();
    const gate = f.holdNextWrite();
    const controller = new AbortController();
    const progress = [];
    const promise = download.download({
        signal: controller.signal,
        onProgress: (value) => progress.push(value),
    });
    const rejection = assert.rejects(promise, { name: 'AbortError' });
    await gate.started.promise;
    const events = progress.length;
    controller.abort();
    gate.release.resolve();
    await rejection;
    assert.equal(progress.length, events);
    assert.equal(f.records.get(DOWNLOAD_URL).offset, BLOCK_BYTES);
    const commit = f.events.findIndex(
        ([type, offset]) => type === 'commit' && offset === BLOCK_BYTES,
    );
    const checkpoint = f.events.findIndex(
        ([type, offset]) => type === 'checkpoint' && offset === BLOCK_BYTES,
    );
    assert.ok(commit < checkpoint);
});

test('pre-aborted and overlapping calls never start another request', async (t) => {
    const f = await downloadFixture(t);
    const download = await f.open();
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(download.download({ signal: controller.signal }), { name: 'AbortError' });
    assert.equal(f.requests.length, 0);
    const active = new AbortController();
    f.setFetch(() => new Promise(() => {}));
    const promise = download.download({ signal: active.signal });
    const rejection = assert.rejects(promise, { name: 'AbortError' });
    await nextTurn();
    await assert.rejects(download.download(), /already running/);
    await assert.rejects(download.reset(), /Cancel the active download/);
    active.abort();
    await rejection;
    assert.equal(f.requests.length, 1);
});

test('storage reconciliation removes orphans and resets missing-file offsets', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    f.files.set('orphan.part', { bytes: new Uint8Array([9]) });
    f.records.set(DOWNLOAD_URL, { url: DOWNLOAD_URL, offset: 3, total: 6, etag: '"v1"' });
    await f.cleanupStaleDownloads();
    assert.equal(f.files.size, 0);
    assert.equal(f.records.get(DOWNLOAD_URL).offset, 0);
});

test('a completed checkpoint materializes the saved file without a network request', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    await f.seed({ bytes: [1, 2, 3] });
    const download = await f.open();
    assert.deepEqual(
        new Uint8Array(await (await download.download()).arrayBuffer()),
        new Uint8Array([1, 2, 3]),
    );
    assert.equal(f.requests.length, 0);
    assert.equal(f.files.size, 0);
    assert.equal(f.records.size, 0);
});

test('a failed checkpoint never makes a later instance trust an unrecorded file block', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    const bytes = new Uint8Array(BLOCK_BYTES + 3).fill(42);
    f.setFetch(() => response(bytes, { 'content-length': String(bytes.length) }));
    const download = await f.open();
    const gate = f.holdNextWrite();
    const error = new DOMException('Database quota exceeded', 'QuotaExceededError');
    const rejection = assert.rejects(download.download(), (value) => value === error);
    await gate.started.promise;
    f.failCheckpoints(error);
    gate.release.resolve();
    await rejection;
    assert.equal(f.records.get(DOWNLOAD_URL).offset, 0);
    assert.equal([...f.files.values()][0].bytes.length, BLOCK_BYTES);

    f.failCheckpoints(undefined);
    const restored = await f.open();
    assert.equal(restored.downloadedBytes, 0);
    assert.equal([...f.files.values()][0].bytes.length, 0);
    assert.deepEqual(new Uint8Array(await (await restored.download()).arrayBuffer()), bytes);
    assert.equal(f.requests[1].headers.has('range'), false);
});
