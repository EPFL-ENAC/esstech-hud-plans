import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const { useCaptureStore, makeEmptyCaptureDraft } = await importTypeScript(
        t,
        'src/stores/capture.ts',
        {
            vue: import.meta.resolve('vue'),
            pinia: import.meta.resolve('pinia'),
            'src/i18n/instance': { i18n: { global: { t: (key) => key } } },
            'src/lib/reconstruction-settings': {
                makeDefaultReconstructionSettings: () => ({
                    ffmpeg: {},
                    framePicker: {},
                    colmap: {},
                    brush: {},
                }),
            },
        },
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    t.after(() => {
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    return { store: useCaptureStore(), makeEmptyCaptureDraft };
}

test('an uploaded video survives a recorder round trip without recording', async (t) => {
    const { store, makeEmptyCaptureDraft } = await fixture(t);
    const draft = makeEmptyCaptureDraft('/capture?buildingId=existing');
    assert.equal(draft.selectedUpload, null);
    const selectedUpload = { id: 'stored-upload', filename: 'stored.mp4' };
    store.saveDraft({ ...draft, selectedUpload });
    assert.equal(store.returnTo, draft.returnTo);
    const restored = store.takeDraft();
    assert.deepEqual(restored.selectedUpload, selectedUpload);
    assert.equal(restored.videoFile, null);
    assert.equal(store.takeDraft(), null);
});

test('a completed recording replaces the uploaded video and retains form settings', async (t) => {
    const { store, makeEmptyCaptureDraft } = await fixture(t);
    const draft = makeEmptyCaptureDraft();
    store.saveDraft({
        ...draft,
        selectedUpload: { id: 'stored-upload' },
        buildingSelection: { buildingId: 'destination' },
        preset: 'outdoors',
    });
    const captured = { file: new File(['video'], 'recording.webm'), durationSeconds: 5 };
    store.setDraftVideo(captured);
    const restored = store.takeDraft();
    assert.equal(restored.selectedUpload, null);
    assert.equal(restored.videoFile, captured.file);
    assert.equal(restored.capturedVideo, captured);
    assert.deepEqual(restored.buildingSelection, { buildingId: 'destination' });
    assert.equal(restored.preset, 'outdoors');
});
