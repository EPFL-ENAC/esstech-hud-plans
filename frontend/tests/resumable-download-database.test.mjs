import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'indexedDB');
    const transactions = [];
    const calls = [];
    let closes = 0;
    globalThis.indexedDB = {
        open(name, version) {
            assert.equal(name, 'hud-resumable-downloads');
            assert.equal(version, 1);
            const request = {
                result: {
                    createObjectStore(name) {
                        calls.push(['create', name]);
                    },
                    transaction(name, mode) {
                        assert.equal(name, 'downloads');
                        const transaction = {
                            mode,
                            request: {},
                            objectStore() {
                                return Object.fromEntries(
                                    ['get', 'put', 'delete'].map((method) => [
                                        method,
                                        (...args) => {
                                            calls.push([method, ...args]);
                                            return transaction.request;
                                        },
                                    ]),
                                );
                            },
                        };
                        transactions.push(transaction);
                        return transaction;
                    },
                    close() {
                        closes++;
                    },
                },
            };
            queueMicrotask(() => {
                request.onupgradeneeded();
                request.onsuccess();
            });
            return request;
        },
    };
    t.after(() => {
        if (previous) Object.defineProperty(globalThis, 'indexedDB', previous);
        else delete globalThis.indexedDB;
    });
    const { DownloadsDatabase } = await importTypeScript(
        t,
        'src/lib/resumableDownload/downloadsDatabase.ts',
        {},
    );
    return { database: new DownloadsDatabase(), transactions, calls, closes: () => closes };
}

test('checkpoint save waits for transaction completion, not request success', async (t) => {
    const f = await fixture(t);
    const record = { url: 'url', committedBytes: 8, totalBytes: 16, etag: '"v1"', complete: false };
    let settled = false;
    const promise = f.database.save(record).then(() => {
        settled = true;
    });
    await nextTurn();
    const transaction = f.transactions[0];
    transaction.request.result = 'url';
    transaction.request.onsuccess?.();
    await nextTurn();
    assert.equal(settled, false);
    assert.equal(f.closes(), 0);
    transaction.oncomplete();
    await promise;
    assert.equal(f.closes(), 1);
    assert.equal(transaction.mode, 'readwrite');
    assert.deepEqual(f.calls, [
        ['create', 'downloads'],
        ['put', record, 'url'],
    ]);
});

test('transaction abort after request success rejects and closes the database', async (t) => {
    const f = await fixture(t);
    const error = new DOMException('Quota exceeded', 'QuotaExceededError');
    const promise = f.database.save({ url: 'url' });
    const rejection = assert.rejects(promise, (value) => value === error);
    await nextTurn();
    const transaction = f.transactions[0];
    transaction.request.onsuccess?.();
    transaction.error = error;
    transaction.onabort();
    await rejection;
    assert.equal(f.closes(), 1);
});

test('get normalizes missing records and delete uses a write transaction', async (t) => {
    const f = await fixture(t);
    const record = { url: 'url', committedBytes: 0, totalBytes: 0, etag: null, complete: true };
    for (const [method, result, expected] of [
        ['get', undefined, null],
        ['get', record, record],
        ['delete', undefined, undefined],
    ]) {
        const promise = f.database[method]('url');
        await nextTurn();
        const transaction = f.transactions.at(-1);
        transaction.request.result = result;
        transaction.oncomplete();
        assert.deepEqual(await promise, expected);
        assert.equal(transaction.mode, method === 'delete' ? 'readwrite' : 'readonly');
    }
    assert.equal(f.closes(), 3);
});
