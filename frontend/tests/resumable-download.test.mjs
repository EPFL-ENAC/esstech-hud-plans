import assert from 'node:assert/strict';
import { getEventListeners } from 'node:events';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { BLOCK_BYTES, DOWNLOAD_URL, downloadFixture } from './helpers/resumable-download.mjs';

function response(bytes, headers = {}) {
    return new Response(bytes, { headers: { etag: '"v1"', ...headers } });
}

async function contents(blob) {
    return [...new Uint8Array(await blob.arrayBuffer())];
}

async function waitFor(condition) {
    for (let attempt = 0; attempt < 1000; attempt++) {
        if (condition()) return;
        await nextTurn();
    }
    throw new Error('Download did not reach the expected stage.');
}

for (const persistent of [false, true]) {
    test(`completed downloads retain their bytes and never refetch: persistent=${persistent}`, async (t) => {
        const f = await downloadFixture(t, { persistent });
        f.setFetch(() => response(new Uint8Array([1, 2, 3]), { 'content-length': '3' }));
        const oldInstance = await f.open();
        const download = await f.open();
        const blob = await download.download();
        assert.equal(blob.size, 3);
        assert.equal(f.events.filter(([type]) => type === 'materialize').length, 0);
        assert.equal(download.downloadedBytes, 3);
        assert.deepEqual(download.metadata, { etag: '"v1"', totalBytes: 3, complete: true });
        const metadata = download.metadata;
        metadata.complete = false;
        assert.equal(download.metadata.complete, true);
        assert.deepEqual(await contents(await download.download()), [1, 2, 3]);
        if (persistent) {
            assert.equal(f.files.size, 1);
            assert.equal(f.records.get(DOWNLOAD_URL).complete, true);
            assert.deepEqual(await contents(await (await f.open()).download()), [1, 2, 3]);
            assert.deepEqual(await contents(await oldInstance.download()), [1, 2, 3]);
        }
        assert.equal(f.requests.length, 1);
        await download.reset();
        assert.equal(download.downloadedBytes, 0);
        assert.equal(download.metadata, null);
        assert.equal(f.records.size, 0);
        assert.equal(f.files.size, 0);
        assert.deepEqual(await contents(await download.download()), [1, 2, 3]);
        assert.equal(f.requests.length, 2);
    });

    for (const size of [0, 3]) {
        test(`unknown length completes and reopens: size=${size}, persistent=${persistent}`, async (t) => {
            const f = await downloadFixture(t, { persistent });
            f.setFetch(() => response(new Uint8Array(size).fill(7)));
            let download = await f.open();
            assert.equal((await download.download()).size, size);
            assert.equal(download.metadata.totalBytes, size);
            if (persistent) download = await f.open();
            assert.equal((await download.download()).size, size);
            assert.equal(f.requests.length, 1);
        });
    }

    test(`cancellation flushes a small tail before retry: persistent=${persistent}`, async (t) => {
        const f = await downloadFixture(t, { persistent });
        const controller = new AbortController();
        const error = new Error('paused');
        let cancelled = false;
        f.setFetch(() =>
            response(
                new ReadableStream({
                    start(stream) {
                        stream.enqueue(new Uint8Array([1, 2, 3]));
                    },
                    cancel() {
                        cancelled = true;
                    },
                }),
                { 'content-length': '6' },
            ),
        );
        let download = await f.open();
        await assert.rejects(
            download.download({
                signal: controller.signal,
                onProgress({ loaded }) {
                    if (loaded === 3) controller.abort(error);
                },
            }),
            (value) => value === error,
        );
        assert.equal(cancelled, true);
        assert.equal(download.downloadedBytes, 3);
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
        if (persistent) {
            assert.equal(f.records.get(DOWNLOAD_URL).committedBytes, 3);
            assert.equal(f.records.get(DOWNLOAD_URL).complete, false);
            download = await f.open();
        }
        f.setFetch(
            () =>
                new Response(new Uint8Array([4, 5, 6]), {
                    status: 206,
                    headers: { etag: '"v1"', 'content-range': 'bytes 3-5/6' },
                }),
        );
        assert.deepEqual(await contents(await download.download()), [1, 2, 3, 4, 5, 6]);
        assert.equal(f.requests[1].headers.get('range'), 'bytes=3-');
        assert.equal(f.requests[1].headers.get('if-range'), '"v1"');
    });

    for (const stage of ['headers', 'first chunk', 'after one chunk']) {
        test(`60-second inactivity timeout: ${stage}, persistent=${persistent}`, async (t) => {
            t.mock.timers.enable({ apis: ['setTimeout'] });
            const f = await downloadFixture(t, { persistent });
            const parent = new AbortController();
            f.setFetch(() =>
                stage === 'headers'
                    ? new Promise(() => {})
                    : response(
                          new ReadableStream({
                              start(stream) {
                                  if (stage === 'after one chunk')
                                      stream.enqueue(new Uint8Array([1, 2, 3]));
                              },
                          }),
                      ),
            );
            const download = await f.open();
            const promise = download.download({ signal: parent.signal });
            const rejection = assert.rejects(promise, { name: 'TimeoutError' });
            await waitFor(() => f.requests.length === 1);
            if (stage === 'after one chunk') await waitFor(() => download.downloadedBytes === 3);
            await nextTurn();
            t.mock.timers.tick(59_999);
            await nextTurn();
            assert.equal(f.requests[0].signal.aborted, false);
            t.mock.timers.tick(1);
            await rejection;
            assert.equal(parent.signal.aborted, false);
            assert.equal(f.requests[0].signal.aborted, true);
            assert.equal(getEventListeners(parent.signal, 'abort').length, 0);
            if (persistent && stage === 'after one chunk') {
                assert.equal(f.records.get(DOWNLOAD_URL).committedBytes, 3);
            }
            f.setFetch(() =>
                stage === 'after one chunk'
                    ? new Response(new Uint8Array([4]), {
                          status: 206,
                          headers: { 'content-range': 'bytes 3-3/4' },
                      })
                    : response(new Uint8Array([4])),
            );
            assert.equal((await download.download()).size, stage === 'after one chunk' ? 4 : 1);
        });
    }

    test(`continuous progress may take over 60 seconds: persistent=${persistent}`, async (t) => {
        t.mock.timers.enable({ apis: ['setTimeout'] });
        const f = await downloadFixture(t, { persistent });
        let stream;
        f.setFetch(() =>
            response(
                new ReadableStream({
                    start(value) {
                        stream = value;
                    },
                }),
            ),
        );
        const download = await f.open();
        const promise = download.download();
        await waitFor(() => stream !== undefined);
        await nextTurn();
        for (const byte of [1, 2, 3]) {
            t.mock.timers.tick(59_000);
            stream.enqueue(new Uint8Array([byte]));
            await nextTurn();
        }
        stream.close();
        assert.deepEqual(await contents(await promise), [1, 2, 3]);
    });

    test(`pre-abort and concurrent operations never issue another request: persistent=${persistent}`, async (t) => {
        const f = await downloadFixture(t, { persistent });
        const download = await f.open();
        const second = await f.open();
        for (const reason of [undefined, null, 0, '']) {
            const preAborted = new AbortController();
            preAborted.abort(reason);
            await assert.rejects(
                download.download({ signal: preAborted.signal }),
                (error) => error === preAborted.signal.reason,
            );
        }
        assert.equal(f.requests.length, 0);
        const controller = new AbortController();
        f.setFetch(() => new Promise(() => {}));
        const promise = download.download({ signal: controller.signal });
        const rejection = assert.rejects(promise, (error) => error === null);
        await waitFor(() => f.requests.length === 1);
        await assert.rejects(download.download(), /already running/);
        await assert.rejects(download.reset(), /already running/);
        await assert.rejects(second.download(), /already being downloaded/);
        await assert.rejects(second.reset(), /already being downloaded/);
        await assert.rejects(f.open(), /already being downloaded/);
        const other = await f.open(`${DOWNLOAD_URL}-different`);
        assert.ok(other);
        controller.abort(null);
        await rejection;
        assert.equal(f.requests.length, 1);
        assert.equal(f.locks.size, 0);
    });
}

test('missing Web Locks falls back to isolated memory storage', async (t) => {
    const f = await downloadFixture(t, { persistent: true, locksAvailable: false });
    f.setFetch(() => response(new Uint8Array([1])));
    assert.equal((await (await f.open()).download()).size, 1);
    assert.equal(f.files.size, 0);
    assert.equal(f.records.size, 0);
});

test('reconcile an unrecorded tail and resume from the saved prefix', async (t) => {
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
    assert.deepEqual(await contents(await download.download()), [1, 2, 3, 4, 5, 6]);
});

for (const missing of [false, true]) {
    test(`completed file that shrank cannot be reused: missing=${missing}`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        const name = await f.seed({ bytes: [1, 2, 3], complete: true });
        if (missing) f.files.delete(name);
        else f.files.set(name, new Uint8Array([1]));
        const download = await f.open();
        assert.equal(download.metadata.complete, false);
        assert.equal(download.downloadedBytes, missing ? 0 : 1);
        assert.equal(f.records.get(DOWNLOAD_URL).committedBytes, missing ? 0 : 1);
        f.setFetch(() =>
            missing
                ? response(new Uint8Array([1, 2, 3]), { 'content-length': '3' })
                : new Response(new Uint8Array([2, 3]), {
                      status: 206,
                      headers: { 'content-range': 'bytes 1-2/3' },
                  }),
        );
        assert.deepEqual(await contents(await download.download()), [1, 2, 3]);
    });
}

for (const status of [200, 416]) {
    test(`HTTP ${status} replaces saved bytes`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        await f.seed({ bytes: [9, 9], total: 6 });
        f.setFetch(() =>
            status === 416 && f.requests.length === 1
                ? new Response(null, { status: 416 })
                : response(new Uint8Array([1, 2]), { etag: '"v2"', 'content-length': '2' }),
        );
        assert.deepEqual(await contents(await (await f.open()).download()), [1, 2]);
        if (status === 416) assert.equal(f.requests[1].headers.has('range'), false);
        assert.equal(f.records.get(DOWNLOAD_URL).etag, '"v2"');
    });
}

for (const etag of [null, '', 'W/"v1"']) {
    test(`incomplete data without a strong validator restarts: etag=${etag}`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        await f.seed({ bytes: [9, 9], total: 3, etag });
        f.setFetch(() => response(new Uint8Array([1, 2, 3])));
        assert.deepEqual(await contents(await (await f.open()).download()), [1, 2, 3]);
        assert.equal(f.requests[0].headers.has('range'), false);
    });
}

for (const headers of [
    { 'content-range': 'bytes 2-5/6', etag: '"v1"' },
    { 'content-range': 'bytes 3-5/6', etag: '"v2"' },
    { 'content-range': 'bytes 3-6/7', etag: '"v1"' },
    { 'content-range': 'bytes 3-4/6', etag: '"v1"' },
    { 'content-range': 'invalid', etag: '"v1"' },
]) {
    test(`invalid resume leaves the saved prefix intact: ${JSON.stringify(headers)}`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        await f.seed({ bytes: [1, 2, 3], total: 6 });
        f.setFetch(() => new Response(new Uint8Array([4, 5, 6]), { status: 206, headers }));
        const download = await f.open();
        await assert.rejects(download.download());
        assert.equal(download.downloadedBytes, 3);
        assert.equal(f.records.get(DOWNLOAD_URL).committedBytes, 3);
    });
}

for (const length of [2, 4]) {
    test(`incorrect body length is never marked complete: length=${length}`, async (t) => {
        const f = await downloadFixture(t, { persistent: true });
        f.setFetch(() => response(new Uint8Array(length), { 'content-length': '3' }));
        const download = await f.open();
        await assert.rejects(download.download(), length < 3 ? /Incomplete download/ : /exceeds/);
        assert.equal(download.metadata.complete, false);
        assert.equal(f.records.get(DOWNLOAD_URL)?.complete ?? false, false);
        assert.equal(download.downloadedBytes, length < 3 ? length : 0);
    });
}

test('cancellation during a block commit finishes checkpointing and suppresses progress', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    f.setFetch(() =>
        response(
            new ReadableStream({
                start(stream) {
                    stream.enqueue(new Uint8Array(BLOCK_BYTES));
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
    const count = progress.length;
    controller.abort();
    gate.release.resolve();
    await rejection;
    assert.equal(progress.length, count);
    assert.equal(f.records.get(DOWNLOAD_URL).committedBytes, BLOCK_BYTES);
    const commit = f.events.findIndex(([type]) => type === 'commit');
    const checkpoint = f.events.findIndex(([type]) => type === 'checkpoint');
    assert.ok(commit < checkpoint);
});

test('checkpoint failure stops without retry; another instance discards the unrecorded block', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    const error = new Error('database unavailable');
    f.failCheckpoints(error);
    f.setFetch(() =>
        response(new Uint8Array(BLOCK_BYTES + 3), { 'content-length': String(BLOCK_BYTES + 3) }),
    );
    await assert.rejects((await f.open()).download(), (value) => value === error);
    assert.equal(f.events.filter(([type]) => type === 'commit').length, 1);
    assert.equal(f.records.size, 0);
    f.failCheckpoints(undefined);
    const download = await f.open();
    assert.equal(download.downloadedBytes, 0);
    assert.equal((await download.download()).size, BLOCK_BYTES + 3);
    assert.equal(f.requests[1].headers.has('range'), false);
});

test('network failure and final persistence failure report both errors', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    const networkError = new Error('network disconnected');
    const saveError = new Error('disk unavailable');
    let stream;
    f.setFetch(() =>
        response(
            new ReadableStream({
                start(value) {
                    stream = value;
                    stream.enqueue(new Uint8Array([1, 2, 3]));
                },
            }),
        ),
    );
    const download = await f.open();
    const promise = download.download({
        onProgress({ loaded }) {
            if (loaded === 3) {
                f.failWrites(saveError);
                stream.error(networkError);
            }
        },
    });
    await assert.rejects(promise, (error) => {
        assert.ok(error instanceof AggregateError);
        assert.deepEqual(error.errors, [networkError, saveError]);
        return true;
    });
    assert.equal(f.requests.length, 1);
});

test('reset invalidates metadata before a removal failure and surfaces the error', async (t) => {
    const f = await downloadFixture(t, { persistent: true });
    await f.seed({ bytes: [1, 2, 3], complete: true });
    const download = await f.open();
    const error = new Error('remove failed');
    f.failRemoval(error);
    await assert.rejects(download.reset(), (value) => value === error);
    assert.equal(download.metadata, null);
    assert.equal(f.records.size, 0);
    assert.equal(f.files.size, 1);
    f.failRemoval(undefined);
    assert.equal((await f.open()).downloadedBytes, 0);
});
