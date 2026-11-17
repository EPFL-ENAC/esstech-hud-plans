import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

const remote = { uploadId: 'remote', uploadUrl: 'https://hud.test/tus/files/remote' };

async function fixture(t) {
    const original = globalThis.BroadcastChannel;
    const channels = new Set();
    const notifications = [];
    globalThis.BroadcastChannel = class {
        closed = false;

        constructor(name) {
            this.name = name;
            channels.add(this);
        }

        postMessage(data) {
            notifications.push(data);
            for (const peer of channels) {
                if (peer !== this && peer.name === this.name && !peer.closed) {
                    peer.onmessage?.({ data: structuredClone(data) });
                }
            }
        }

        close() {
            this.closed = true;
        }
    };
    t.after(() => {
        globalThis.BroadcastChannel = original;
        assert.equal(
            [...channels].every((channel) => channel.closed),
            true,
        );
    });
    const module = await importTypeScript(t, 'src/lib/localUploadsRegistry.ts', {
        'src/lib/api': { ApiError: class extends Error {} },
    });
    const registry = new module.LocalUploadsRegistry();
    let savedRemote = null;
    const reads = t.mock.method(registry, 'get', async (ownerId, id) => ({
        ownerId,
        id,
        remote: savedRemote,
    }));
    const sender = new module.LocalUploadsRegistry();
    t.mock.method(sender, 'transaction', async () => {
        savedRemote = remote;
    });
    const controller = new AbortController();
    t.after(() => controller.abort());
    return { registry, sender, controller, reads, channels, notifications, ...module };
}

test('an existing remote ID resolves immediately and closes its channel', async (t) => {
    const f = await fixture(t);
    await f.sender.setRemote('owner', 'local', remote);
    assert.deepEqual(await f.registry.waitForRemote('owner', 'local', f.controller.signal), remote);
    assert.equal(f.reads.mock.callCount(), 1);
});

test('notifications from another instance wake only the matching owner and upload', async (t) => {
    const f = await fixture(t);
    const waiting = f.registry.waitForRemote('owner', 'local', f.controller.signal);
    await nextTurn();
    await f.sender.setRemote('other-owner', 'local', remote);
    await f.sender.setRemote('owner', 'other-local', remote);
    await nextTurn();
    assert.equal(f.reads.mock.callCount(), 1);
    await f.sender.setRemote('owner', 'local', remote);
    assert.deepEqual(await waiting, remote);
    assert.equal(f.reads.mock.callCount(), 2);
});

test('an assignment during the initial read is not missed', async (t) => {
    const f = await fixture(t);
    const initialRead = deferred();
    f.reads.mock.mockImplementationOnce(() => initialRead.promise);
    const waiting = f.registry.waitForRemote('owner', 'local', f.controller.signal);
    await f.sender.setRemote('owner', 'local', remote);
    assert.deepEqual(await waiting, remote);
    initialRead.resolve({ remote: null });
    await nextTurn();
    assert.equal(f.reads.mock.callCount(), 2);
});

test('setRemote publishes only after commit and does not publish a failed write', async (t) => {
    const f = await fixture(t);
    const commit = deferred();
    t.mock.method(f.sender, 'transaction', () => commit.promise);
    const saving = f.sender.setRemote('owner', 'local', remote);
    assert.deepEqual(f.notifications, []);
    commit.resolve();
    await saving;
    assert.deepEqual(f.notifications, [{ ownerId: 'owner', localUploadId: 'local' }]);

    t.mock.method(f.sender, 'transaction', async () => {
        throw new f.LocalUploadStorageError(new Error('Write failed'));
    });
    await assert.rejects(f.sender.setRemote('owner', 'local', remote), f.LocalUploadStorageError);
    assert.equal(f.notifications.length, 1);
});

test('aborting removes the listener and ignores notifications and late reads', async (t) => {
    const f = await fixture(t);
    const read = deferred();
    f.reads.mock.mockImplementation(() => read.promise);
    const remove = t.mock.method(f.controller.signal, 'removeEventListener');
    const waiting = f.registry.waitForRemote('owner', 'local', f.controller.signal);
    const rejected = assert.rejects(waiting, { name: 'AbortError' });
    f.controller.abort();
    await rejected;
    assert.equal(remove.mock.callCount(), 1);
    await f.sender.setRemote('owner', 'local', remote);
    read.resolve({ remote });
    await nextTurn();
    assert.equal(f.reads.mock.callCount(), 1);
});

test('an already aborted wait opens no channel or database read', async (t) => {
    const f = await fixture(t);
    f.controller.abort();
    assert.throws(() => f.registry.waitForRemote('owner', 'local', f.controller.signal), {
        name: 'AbortError',
    });
    assert.equal(f.channels.size, 0);
    assert.equal(f.reads.mock.callCount(), 0);
});

for (const storageFailure of [false, true]) {
    test(`a ${storageFailure ? 'storage error' : 'missing upload'} rejects and cleans up`, async (t) => {
        const f = await fixture(t);
        const error = storageFailure
            ? new f.LocalUploadStorageError(new Error('Read failed'))
            : new Error('Local upload is missing.');
        f.reads.mock.mockImplementation(async () => {
            throw error;
        });
        await assert.rejects(
            f.registry.waitForRemote('owner', 'local', f.controller.signal),
            (failure) => failure === error,
        );
    });
}
