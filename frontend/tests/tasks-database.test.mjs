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
            assert.equal(name, 'hud-network-tasks');
            assert.equal(version, 1);
            const request = {
                result: {
                    createObjectStore(name, options) {
                        calls.push(['store', name, options]);
                        return { createIndex: (...args) => calls.push(['index', ...args]) };
                    },
                    close() {
                        closes++;
                    },
                    transaction(names, mode) {
                        assert.deepEqual(names, ['tasks', 'files']);
                        const transaction = {
                            requests: [],
                            mode,
                            abort() {
                                this.onabort();
                            },
                            objectStore(store) {
                                const operation = (method, ...args) => {
                                    calls.push([store, method, ...args]);
                                    const request = {};
                                    transaction.requests.push(request);
                                    return request;
                                };
                                return {
                                    add: (...args) => operation('add', ...args),
                                    put: (...args) => operation('put', ...args),
                                    get: (...args) => operation('get', ...args),
                                    clear: () => operation('clear'),
                                    delete: (...args) => operation('delete', ...args),
                                    openKeyCursor: (...args) => operation('openKeyCursor', ...args),
                                    index: (name) => ({
                                        getAll: (ownerId) => operation('getAll', name, ownerId),
                                    }),
                                };
                            },
                        };
                        transactions.push(transaction);
                        return transaction;
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
    const { TasksDatabase } = await importTypeScript(t, 'src/lib/tasksDatabase.ts', {});
    return { database: new TasksDatabase(), transactions, calls, closes: () => closes };
}

test('creating a task and File is one transaction and waits for commit', async (t) => {
    const f = await fixture(t);
    const snapshot = { id: 'task', ownerId: 'owner' };
    const file = new File(['video'], 'scan.mp4');
    let settled = false;
    const promise = f.database.create({ snapshot, files: { video: file } }).then(() => {
        settled = true;
    });
    await nextTurn();
    const transaction = f.transactions[0];
    for (const request of transaction.requests) request.onsuccess?.();
    assert.equal(settled, false);
    assert.equal(transaction.mode, 'readwrite');
    assert.deepEqual(f.calls.slice(-2), [
        ['tasks', 'add', snapshot],
        ['files', 'add', file, ['owner', 'task', 'video']],
    ]);
    transaction.oncomplete();
    await promise;
    assert.equal(settled, true);
    assert.equal(f.closes(), 1);
});

test('metadata checkpoints never rewrite attached files and aborted commits reject', async (t) => {
    const f = await fixture(t);
    const error = new DOMException('Full', 'QuotaExceededError');
    const snapshot = { id: 'task', ownerId: 'owner' };
    const rejected = assert.rejects(f.database.save(snapshot), (value) => value === error);
    await nextTurn();
    const transaction = f.transactions[0];
    transaction.requests[0].result = snapshot;
    transaction.requests[0].onsuccess();
    transaction.error = error;
    transaction.onabort();
    await rejected;
    assert.deepEqual(f.calls.slice(-2), [
        ['tasks', 'get', ['owner', 'task']],
        ['tasks', 'put', snapshot],
    ]);
    assert.equal(f.closes(), 1);
});

test('restoration queries the owner index and reports missing attachments', async (t) => {
    const f = await fixture(t);
    const promise = f.database.list('owner');
    await nextTurn();
    f.transactions[0].requests[0].result = [];
    f.transactions[0].oncomplete();
    assert.deepEqual(await promise, []);
    assert.deepEqual(f.calls.at(-1), ['tasks', 'getAll', 'ownerId', 'owner']);
    const rejected = assert.rejects(f.database.files('owner', 'task').get('video'), /missing/);
    await nextTurn();
    f.transactions[1].requests[0].result = undefined;
    f.transactions[1].oncomplete();
    await rejected;
});

test('database operations wait for earlier commits and a failed write does not stop the queue', async (t) => {
    const f = await fixture(t);
    const snapshot = { id: 'task', ownerId: 'owner' };
    const first = f.database.create({ snapshot });
    const rejected = assert.rejects(first, /Storage failed/);
    const second = f.database.save(snapshot);
    await nextTurn();
    assert.equal(f.transactions.length, 1);
    f.transactions[0].error = new Error('Storage failed');
    f.transactions[0].onabort();
    await rejected;
    await nextTurn();
    assert.equal(f.transactions.length, 2);
    const transaction = f.transactions[1];
    transaction.requests[0].result = snapshot;
    transaction.requests[0].onsuccess();
    transaction.oncomplete();
    await second;
    assert.deepEqual(f.calls.at(-1), ['tasks', 'put', snapshot]);
});

test('a late checkpoint cannot recreate a missing record', async (t) => {
    const f = await fixture(t);
    const saving = f.database.save({ id: 'deleted', ownerId: 'owner' });
    await nextTurn();
    const transaction = f.transactions[0];
    transaction.requests[0].result = undefined;
    transaction.requests[0].onsuccess();
    transaction.oncomplete();
    await saving;
    assert.equal(
        f.calls.some(([, method]) => method === 'put'),
        false,
    );
});

test('clearing closes admission immediately and drains transactions before erasing records', async (t) => {
    const f = await fixture(t);
    const creating = f.database.create({ snapshot: { id: 'task', ownerId: 'owner' } });
    await nextTurn();
    const clearing = f.database.clearAndClose();
    await assert.rejects(f.database.save({ id: 'task', ownerId: 'owner' }), /closed/);
    await assert.rejects(f.database.list('owner'), /closed/);
    await assert.rejects(f.database.files('owner', 'task').get('video'), /closed/);
    assert.equal(f.transactions.length, 1);
    f.transactions[0].oncomplete();
    await creating;
    await nextTurn();
    assert.equal(f.transactions.length, 2);
    assert.deepEqual(f.calls.slice(-2), [
        ['tasks', 'clear'],
        ['files', 'clear'],
    ]);
    f.transactions[1].oncomplete();
    await clearing;
    await assert.rejects(
        f.database.create({ snapshot: { id: 'late', ownerId: 'owner' } }),
        /closed/,
    );
    assert.equal(f.transactions.length, 2);
});
