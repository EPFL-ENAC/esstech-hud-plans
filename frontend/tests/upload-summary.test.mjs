import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { computed, effectScope, reactive, ref, shallowReactive } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

class VideoUploadTask {
    state = reactive({ status: 'queued', progress: null });

    constructor(ownerId, localUploadId) {
        this.ownerId = ownerId;
        this.localUploadId = localUploadId;
    }
}

function localRecord(id, remote = null) {
    return { id, ownerId: 'owner', file: { name: `${id}.mp4`, size: 100 }, remote };
}

function serverUpload(id, status, bytes) {
    return { id, filename: `${id}.mp4`, size_bytes: 100, uploaded_bytes: bytes, status };
}

async function fixture(t, uploadReference) {
    const reference = ref(uploadReference);
    const ownerId = ref('owner');
    const isAuthenticated = ref(true);
    const queue = shallowReactive({ tasks: [] });
    const reads = [];
    const waits = [];
    const remoteStates = reactive(new Map());
    const remoteRetries = [];
    let remoteId;

    const { useUploadSummary } = await importTypeScript(t, 'src/composables/useUploadSummary.ts', {
        vue: import.meta.resolve('vue'),
        'src/composables/useAuthentication': {
            useAuthentication: () => ({ ownerId, isAuthenticated }),
        },
        'src/lib/localUploadsRegistry': {
            LocalUploadsRegistry: class {
                get(owner, id) {
                    const gate = deferred();
                    reads.push({ owner, id, gate });
                    return gate.promise;
                }

                waitForRemote(owner, id, signal) {
                    const gate = deferred();
                    waits.push({ owner, id, signal, gate });
                    return gate.promise;
                }
            },
        },
        'src/lib/videoUploadTask': { VideoUploadTask },
        'src/queries/uploads': {
            useUploadQuery(id) {
                remoteId = id;
                return {
                    state: computed(
                        () => remoteStates.get(id.value) ?? { status: 'pending', error: null },
                    ),
                    asyncStatus: computed(() => (id.value ? 'loading' : 'idle')),
                    refetch: () => remoteRetries.push(id.value),
                };
            },
        },
        'src/stores/networkDependentTasks': { useNetworkDependentTasks: () => queue },
    });
    const scope = effectScope();
    t.after(() => scope.stop());
    return {
        ...scope.run(() => useUploadSummary(reference)),
        reference,
        ownerId,
        queue,
        reads,
        waits,
        remoteId,
        remoteStates,
        remoteRetries,
        stop: () => scope.stop(),
    };
}

test('a direct remote ID reads and refreshes server data without accessing the registry', async (t) => {
    const f = await fixture(t, { uploadId: 'remote' });
    assert.equal(f.remoteId.value, 'remote');
    assert.equal(f.state.value.status, 'pending');
    f.remoteStates.set('remote', {
        status: 'success',
        data: serverUpload('remote', 'pending', 25),
    });
    assert.deepEqual(f.state.value, {
        status: 'success',
        error: null,
        data: {
            filename: 'remote.mp4',
            sizeBytes: 100,
            status: { source: 'server', value: 'pending' },
            progress: { loaded: 25, total: 100 },
        },
    });

    f.refetch();
    assert.deepEqual(f.remoteRetries, ['remote']);
    f.reference.value = { uploadId: 'another' };
    assert.equal(f.state.value.status, 'pending');
    assert.equal(f.state.value.data, undefined);
    assert.deepEqual(f.reads, []);
    assert.deepEqual(f.waits, []);
});

test('an already-linked local record shows the backup until the server query succeeds', async (t) => {
    const f = await fixture(t, { localUploadId: 'local' });
    f.reads[0].gate.resolve(localRecord('local', { uploadId: 'remote' }));
    await nextTurn();

    assert.equal(f.remoteId.value, 'remote');
    assert.deepEqual(f.state.value.data.status, { source: 'device' });
    assert.deepEqual(f.waits, []);
    f.remoteStates.set('remote', {
        status: 'success',
        data: serverUpload('remote', 'uploaded', 100),
    });
    assert.equal(f.state.value.data.filename, 'remote.mp4');
    assert.deepEqual(f.state.value.data.status, { source: 'server', value: 'uploaded' });
    assert.equal(f.state.value.data.progress, null);
});

test('the local card follows the matching task and survives a failed server lookup', async (t) => {
    const f = await fixture(t, { localUploadId: 'local' });
    const task = new VideoUploadTask('owner', 'local');
    f.queue.tasks = [
        new VideoUploadTask('someone-else', 'local'),
        new VideoUploadTask('owner', 'other-id'),
        task,
    ];
    f.reads[0].gate.resolve(localRecord('local'));
    await nextTurn();

    assert.equal(f.remoteId.value, '');
    assert.equal(f.asyncStatus.value, 'idle');
    assert.deepEqual(f.state.value.data.status, { source: 'task', value: 'queued' });
    task.state.status = 'running';
    task.state.progress = { completed: 10, total: null };
    assert.deepEqual(f.state.value.data.progress, { loaded: 10, total: 100 });
    task.state.status = 'failed';
    assert.deepEqual(f.state.value.data.status, { source: 'task', value: 'failed' });
    assert.equal(f.state.value.data.progress, null);

    f.waits[0].gate.resolve({ uploadId: 'remote' });
    await nextTurn();
    f.remoteStates.set('remote', { status: 'error', error: new Error('Offline') });
    assert.equal(f.state.value.status, 'error');
    assert.equal(f.state.value.data.filename, 'local.mp4');
    f.refetch();
    assert.deepEqual(f.remoteRetries, ['remote']);
    assert.equal(f.reads.length, 1);

    f.remoteStates.set('remote', {
        status: 'success',
        data: serverUpload('remote', 'pending', 40),
    });
    assert.equal(f.state.value.data.filename, 'remote.mp4');
    assert.deepEqual(f.state.value.data.progress, { loaded: 40, total: 100 });
});

test('retrying a local lookup also restarts the wait for a remote ID', async (t) => {
    const f = await fixture(t, { localUploadId: 'local' });
    f.reads[0].gate.reject(new Error('Storage error'));
    await nextTurn();
    assert.equal(f.state.value.status, 'error');
    assert.equal(f.state.value.data, undefined);

    f.refetch();
    assert.equal(f.asyncStatus.value, 'loading');
    f.reads[1].gate.resolve(localRecord('local'));
    await nextTurn();
    f.waits[0].gate.reject(new Error('Could not watch the upload'));
    await nextTurn();
    assert.equal(f.state.value.status, 'error');
    assert.equal(f.state.value.data.filename, 'local.mp4');

    f.refetch();
    f.reads[2].gate.resolve(localRecord('local', { uploadId: 'remote' }));
    await nextTurn();
    assert.deepEqual(
        f.reads.map(({ owner, id }) => [owner, id]),
        Array.from({ length: 3 }, () => ['owner', 'local']),
    );
    assert.equal(f.remoteId.value, 'remote');
    assert.deepEqual(f.remoteRetries, []);
});

test('changing the reference ignores abandoned metadata and aborts the old remote wait', async (t) => {
    const f = await fixture(t, { localUploadId: 'first' });
    f.reference.value = { localUploadId: 'second' };
    f.reads[0].gate.resolve(localRecord('first', { uploadId: 'wrong-server-id' }));
    await nextTurn();
    assert.equal(f.remoteId.value, '');
    assert.equal(f.state.value.data, undefined);

    f.reads[1].gate.resolve(localRecord('second'));
    await nextTurn();
    assert.equal(f.state.value.data.filename, 'second.mp4');
    f.reference.value = { uploadId: 'right-server-id' };
    assert.equal(f.waits[0].signal.aborted, true);
    f.waits[0].gate.resolve({ uploadId: 'wrong-server-id' });
    await nextTurn();
    assert.equal(f.remoteId.value, 'right-server-id');
    assert.equal(f.state.value.data, undefined);
});

for (const cleanup of ['account change', 'unmount']) {
    test(`${cleanup} aborts the local wait`, async (t) => {
        const f = await fixture(t, { localUploadId: 'local' });
        f.reads[0].gate.resolve(localRecord('local'));
        await nextTurn();
        const { gate, signal } = f.waits[0];

        if (cleanup === 'account change') {
            f.ownerId.value = 'someone-else';
            assert.equal(f.state.value.data, undefined);
            assert.equal(f.state.value.status, 'error');
        } else {
            f.stop();
        }
        assert.equal(signal.aborted, true);
        gate.resolve({ uploadId: 'abandoned' });
        await nextTurn();
        assert.equal(f.remoteId.value, '');
    });
}
