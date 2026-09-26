import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

function stubModule(code) {
    return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

async function transpile(path, replacements) {
    const { outputText } = ts.transpileModule(
        readFileSync(new URL(path, import.meta.url), 'utf8'),
        { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
    );
    let source = outputText;
    for (const [from, to] of Object.entries(replacements)) {
        source = source.replaceAll(from, to);
    }
    return stubModule(source);
}

const { ref } = await import('vue');

const store = await transpile('../src/lib/localTransfers.ts', {
    "from 'vue'": `from '${import.meta.resolve('vue')}'`,
});

test('probe returns false when IndexedDB is unavailable', async () => {
    if ('indexedDB' in globalThis) {
        // A plain node run has no indexedDB; a global one must still probe.
        return;
    }
    assert.equal(await store.probeIndexedDb(), false);
});

test('storage helpers no-op safely and never throw without IndexedDB', async () => {
    const record = {
        sessionId: 's-1',
        file: new Blob(),
        plan: [],
        fingerprint: { name: 'v.mp4', size: 1, lastModified: 2 },
        updatedAt: Date.now(),
    };
    await store.saveUploadSession(record);
    assert.equal(await store.getUploadSession('s-1'), null);
    await store.deleteUploadSession('s-1');

    await store.saveDownloadChunk({ id: 'k:0', key: 'k', index: 0, blob: new Blob(), size: 1 });
    await store.saveDownloadMeta({ key: 'k', url: 'u', total: 0, etag: null, receivedBytes: 0 });
    assert.equal(await store.getDownloadChunk('k', 0), null);
    assert.equal(await store.getDownloadMeta('k'), null);
    assert.equal(await store.getDownloadStoredBytes('k'), 0);
    assert.deepEqual(await store.listDownloadChunks('k'), []);
    await store.deleteDownloadData('k');
    await store.evictStaleUploadSessions(0);
});

test('download chunk ids stay addressable per key and index', () => {
    assert.equal(store.downloadChunkId('splat:b:1', 3), 'splat:b:1:3');
    assert.equal(store.downloadChunkId('k', 0), 'k:0');
});

test('waitForResume resolves resumed when the state leaves paused', async () => {
    const state = ref('paused');
    const wait = store.waitForResume(() => state.value);
    state.value = 'uploading';
    assert.equal(await wait, 'resumed');
});

test('waitForResume resolves cancelled when the pass ends without resume', async () => {
    const state = ref('paused');
    const wait = store.waitForResume(() => state.value);
    state.value = 'idle';
    assert.equal(await wait, 'cancelled');
});

test('waitForResume resolves cancelled when the stop signal aborts', async () => {
    const state = ref('paused');
    const controller = new AbortController();
    const wait = store.waitForResume(() => state.value, controller.signal);
    controller.abort();
    assert.equal(await wait, 'cancelled');
});
