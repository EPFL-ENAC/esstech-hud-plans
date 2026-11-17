import assert from 'node:assert/strict';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const api = {
        ApiError: class extends Error {},
        requestJson() {
            assert.fail('Unexpected JSON request');
        },
    };
    const tasks = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/api': api,
        'src/lib/resumableDownload': { ResumableDownload: {} },
    });
    const reconstruction = await importTypeScript(t, 'src/lib/reconstructionSubmissionTask.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/api': api,
        'src/lib/buildings': buildings,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/idempotentRequests': {
            requestIdempotentJson() {},
            idempotentRequestFailureAction() {
                return 'failed';
            },
        },
    });
    const video = await importTypeScript(t, 'src/lib/videoUploadTask.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/api': api,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/idempotentRequests': {
            idempotentRequestFailureAction() {
                return 'failed';
            },
        },
        'src/lib/utils/taskTusUpload': {
            async uploadVideoTus(file, options) {
                const uploadUrl = options.uploadUrl ?? 'https://hud.test/tus/files/video';
                await options.onCheckpoint(uploadUrl);
                const result = {
                    uploadId: 'video',
                    uploadUrl,
                    resumed: options.uploadUrl !== null,
                };
                options.onUploadAvailable(result);
                return result;
            },
        },
    });
    const registry = await importTypeScript(t, 'src/lib/taskRegistry.ts', {
        'src/lib/reconstructionSubmissionTask': reconstruction,
        'src/lib/videoUploadTask': video,
    });
    return { ...reconstruction, ...video, ...registry };
}

for (const buildingId of ['existing', null]) {
    test(`reconstruction ${buildingId} round-trips immutable input, identity, state and no callbacks`, async (t) => {
        const f = await fixture(t);
        const submission = {
            buildingId,
            ...(buildingId === null
                ? { building: { name: 'Original', latitude: null, longitude: null } }
                : {}),
            uploadId: 'upload',
            settings: { ffmpeg: { fps: 4 } },
        };
        const task = new f.ReconstructionSubmissionTask({
            id: 'fixed-id',
            createdAt: 123,
            ownerId: 'owner',
            label: 'Reconstruct',
            submission,
            onCompleted() {
                assert.fail('Callbacks must not be restored');
            },
        });
        submission.settings.ffmpeg.fps = 99;
        const { snapshot } = task.serialize();
        snapshot.state.status = 'running';
        snapshot.state.attempts = 3;
        const restored = f.ReconstructionSubmissionTask.deserialize(structuredClone(snapshot));
        assert.equal(restored.id, task.id);
        assert.equal(restored.createdAt, 123);
        assert.equal(restored.state.status, 'queued');
        assert.equal(restored.state.attempts, 3);
        assert.equal(restored.serialize().snapshot.data.submission.settings.ffmpeg.fps, 4);
        assert.deepEqual(Object.keys(restored.serialize().snapshot).sort(), [
            'createdAt',
            'data',
            'id',
            'label',
            'ownerId',
            'state',
            'type',
        ]);
        assert.equal(JSON.stringify(snapshot).includes('onCompleted'), false);
        snapshot.data.submission.settings.ffmpeg.fps = 1000;
        assert.equal(task.serialize().snapshot.data.submission.settings.ffmpeg.fps, 4);
    });
}

test('video round-trips the File, exact URL, upload state and identity without callbacks', async (t) => {
    const f = await fixture(t);
    const file = new File(['video bytes'], 'scan.mp4', { type: 'video/mp4', lastModified: 42 });
    const task = new f.VideoUploadTask({
        id: 'video-id',
        createdAt: 123,
        ownerId: 'owner',
        label: 'Upload',
        file,
        onCompleted() {
            assert.fail('Callback must not be restored');
        },
        onUploadAvailable() {
            assert.fail('Callback must not be restored');
        },
    });
    const serialized = task.serialize();
    serialized.snapshot.data = {
        uploadUrl: 'https://hud.test/tus/files/video',
        uploadState: { uploadId: 'video', resumed: true },
    };
    serialized.snapshot.state.status = 'pausing';
    serialized.snapshot.state.progress = { completed: 5, total: file.size };
    const restored = await f.deserializeTask(structuredClone(serialized.snapshot), {
        async get(name) {
            assert.equal(name, 'video');
            return serialized.files.video;
        },
    });
    assert.equal(restored.id, task.id);
    assert.equal(restored.createdAt, 123);
    assert.equal(restored.state.status, 'queued');
    assert.deepEqual(restored.uploadState, { uploadId: 'video', resumed: true });
    assert.equal(await restored.file.text(), 'video bytes');
    assert.equal(restored.file.name, 'scan.mp4');
    assert.equal(restored.file.lastModified, 42);
    assert.deepEqual(await restored.retryOrResume(), { uploadId: 'video', resumed: true });
});

test('unknown types and missing files reject restoration', async (t) => {
    const f = await fixture(t);
    const task = new f.VideoUploadTask({
        ownerId: 'owner',
        label: 'Upload',
        file: new File(['x'], 'x.mp4'),
    });
    const snapshot = task.serialize().snapshot;
    const files = {
        async get() {
            throw new Error('File missing');
        },
    };
    await assert.rejects(f.deserializeTask({ ...snapshot, type: 'unknown' }, files), /Unknown/);
    await assert.rejects(f.deserializeTask(snapshot, files), /File missing/);
});
