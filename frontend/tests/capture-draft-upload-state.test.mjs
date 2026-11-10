import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { effectScope } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function loadService(t) {
    return importTypeScript(t, 'src/lib/captureDraftService.ts', {
        './reconstruction-settings': { makeDefaultReconstructionSettings: () => ({}) },
    });
}

const owner = { ownerId: 'owner' };
const starting = { localVideo: true, phase: 'uploading' };
const linked = { phase: 'uploading', uploadId: 'upload-id' };
const uploaded = { uploadId: 'upload-id', completed: true };

function controlWrites(t, service) {
    let metadata = { source: { localVideo: true } };
    const commits = [];
    t.mock.method(service, 'transact', (_stores, _mode, run) => {
        const commit = deferred();
        const request = { result: metadata };
        let written;
        const drafts = {
            get: () => request,
            put: (value) => {
                written = value;
            },
        };
        run({ objectStore: (name) => (name === 'drafts' ? drafts : { delete() {} }) });
        request.onsuccess();
        commits.push(commit);
        return commit.promise.then(() => {
            metadata = written;
        });
    });
    return commits;
}

test('draft source notifications follow commits and isolate accounts and drafts', async (t) => {
    const { CaptureDraftService } = await loadService(t);
    const writer = new CaptureDraftService();
    const reader = new CaptureDraftService();
    const commits = controlWrites(t, writer);
    const update = (change) => writer.updateUpload('draft-id', { ...owner, change });
    const received = [];
    const other = t.mock.fn();
    t.after(reader.listenForUploadChanges('other-draft', owner, other));
    t.after(reader.listenForUploadChanges('draft-id', { ownerId: 'other-owner' }, other));

    const unsubscribe = reader.listenForUploadChanges('draft-id', owner, (source) =>
        received.push(source),
    );
    t.after(unsubscribe);
    const start = update({ phase: 'uploading' });
    assert.deepEqual(received, []);
    commits[0].resolve();
    await start;
    assert.deepEqual(received, [starting]);

    const link = update(linked);
    const rejected = assert.rejects(link, /Aborted/);
    commits[1].reject(new Error('Aborted'));
    await rejected;
    assert.deepEqual(received, [starting]);
    unsubscribe();
    const late = t.mock.fn();
    t.after(reader.listenForUploadChanges('draft-id', owner, late));
    assert.equal(late.mock.callCount(), 0);
    const complete = update({ phase: 'uploaded', uploadId: 'upload-id' });
    commits[2].resolve();
    await complete;
    assert.deepEqual(late.mock.calls[0].arguments, [uploaded]);
    assert.deepEqual(received, [starting]);
    assert.equal(other.mock.callCount(), 0);
});

test('the editor applies a link received during its initial read and preserves the form', async (t) => {
    const serviceModule = await loadService(t);
    const { CaptureDraftService } = serviceModule;
    const stored = deferred();
    const get = t.mock.method(CaptureDraftService.prototype, 'get', () => stored.promise);
    const autosave = await importTypeScript(t, 'src/composables/useDebouncedAutosave.ts', {
        vue: import.meta.resolve('vue'),
    });
    const { useCaptureDraft } = await importTypeScript(t, 'src/composables/useCaptureDraft.ts', {
        vue: import.meta.resolve('vue'),
        'vue-router': { onBeforeRouteLeave() {}, onBeforeRouteUpdate() {} },
        'src/lib/auth': { getAuthSubject: () => owner.ownerId },
        'src/lib/captureDraftService': serviceModule,
        './useDebouncedAutosave': autosave,
    });
    const scope = effectScope();
    t.after(() => scope.stop());
    const editor = scope.run(() => useCaptureDraft('draft-id'));
    const service = new CaptureDraftService();
    const commits = controlWrites(t, service);
    async function update(change) {
        const write = service.updateUpload('draft-id', { ...owner, change });
        commits.at(-1).resolve();
        await write;
    }

    await update(linked);
    assert.equal(editor.loadStatus.value, 'loading');
    stored.resolve({
        id: 'draft-id',
        source: { video: new Blob(['video']) },
        form: { preset: 'indoors' },
    });
    await nextTurn();
    assert.deepEqual(editor.draft.value.source, linked);

    const form = editor.draft.value.form;
    form.preset = 'advanced';
    await update({ phase: 'uploaded', uploadId: 'upload-id' });
    assert.deepEqual(editor.draft.value.source, uploaded);
    assert.equal(editor.draft.value.form, form);
    assert.equal(form.preset, 'advanced');

    scope.stop();
    await update({ phase: 'uploaded', uploadId: 'later-id' });
    assert.deepEqual(editor.draft.value.source, uploaded);
    assert.equal(get.mock.callCount(), 1);
});
