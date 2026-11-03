import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'indexedDB');
    const calls = [];
    const transactions = [];
    let closes = 0;
    globalThis.indexedDB = {
        open(name, version) {
            assert.equal(name, 'hud-downloads');
            assert.equal(version, 3);
            const request = {
                result: {
                    objectStoreNames: { contains: () => true },
                    transaction(storeName, mode) {
                        assert.equal(storeName, 'downloads');
                        const transaction = {
                            mode,
                            request: {},
                            objectStore() {
                                return Object.fromEntries(
                                    ['get', 'put', 'delete', 'getAll'].map((method) => [
                                        method,
                                        (...args) => {
                                            calls.push({ method, args });
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
            queueMicrotask(() => request.onsuccess());
            return request;
        },
    };
    t.after(() => {
        if (previous) Object.defineProperty(globalThis, 'indexedDB', previous);
        else delete globalThis.indexedDB;
    });
    const { DownloadsDatabase } = await importTypeScript(
        t,
        'src/lib/downloads/downloadsDatabase.ts',
        {},
    );
    return { database: new DownloadsDatabase(), transactions, calls, closes: () => closes };
}

test('a successful put does not settle save until the transaction commits', async (t) => {
    const f = await fixture(t);
    const record = { url: 'url', offset: 8, total: 16, etag: '"v1"' };
    let settled = false;
    const save = f.database.save(record).then(() => {
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
    await save;
    assert.equal(settled, true);
    assert.equal(f.closes(), 1);
    assert.equal(transaction.mode, 'readwrite');
    assert.deepEqual(f.calls, [{ method: 'put', args: [record, 'url'] }]);
});

test('a transaction abort after request success rejects save and closes the connection', async (t) => {
    const f = await fixture(t);
    const error = new DOMException('Quota exceeded', 'QuotaExceededError');
    const save = f.database.save({ url: 'url', offset: 1, total: 2, etag: '"v1"' });
    const rejection = assert.rejects(save, (value) => value === error);
    await nextTurn();
    const transaction = f.transactions[0];
    transaction.request.onsuccess?.();
    transaction.error = error;
    transaction.onabort();
    await rejection;
    assert.equal(f.closes(), 1);
});

test('get, list, and delete use their own transactions and normalize absent records', async (t) => {
    const f = await fixture(t);
    const records = [{ url: 'url', offset: 1, total: 2, etag: '"v1"' }];
    for (const [method, result, expected] of [
        ['get', undefined, null],
        ['list', records, records],
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
