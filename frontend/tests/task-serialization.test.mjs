import assert from 'node:assert/strict';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';
import { MemoryLocalUploadsRegistry } from './helpers/localUploadsRegistry.mjs';

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
    const localUploads = await importTypeScript(t, 'src/lib/localUploadsRegistry.ts', {
        'src/lib/api': api,
    });
    const reconstruction = await importTypeScript(t, 'src/lib/reconstructionSubmissionTask.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/api': api,
        'src/lib/buildings': buildings,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/localUploadsRegistry': localUploads,
        'src/lib/idempotentRequests': {
            requestIdempotentJson() {},
            idempotentRequestFailureAction() {
                return 'failed';
            },
        },
    });
    const uploads = new MemoryLocalUploadsRegistry();
    const video = await importTypeScript(t, 'src/lib/videoUploadTask.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/api': api,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/idempotentRequests': {
            idempotentRequestFailureAction() {
                return 'failed';
            },
        },
        'src/lib/localUploadsRegistry': localUploads,
        'src/lib/utils/taskTusUpload': {
            async uploadVideoTus(file, options) {
                const uploadUrl = options.uploadUrl ?? 'https://hud.test/tus/files/video';
                if (options.uploadUrl === null) {
                    await options.onCheckpoint({ uploadId: 'video', uploadUrl });
                }
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
    return { ...reconstruction, ...video, ...registry, uploads };
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
            uploads: f.uploads,
            onCompleted() {
                assert.fail('Callbacks must not be restored');
            },
        });
        submission.settings.ffmpeg.fps = 99;
        const snapshot = task.serialize();
        snapshot.state.status = 'running';
        snapshot.state.attempts = 3;
        const restored = f.ReconstructionSubmissionTask.deserialize(
            structuredClone(snapshot),
            f.uploads,
        );
        assert.equal(restored.id, task.id);
        assert.equal(restored.createdAt, 123);
        assert.equal(restored.state.status, 'queued');
        assert.equal(restored.state.attempts, 3);
        assert.equal(restored.serialize().data.submission.settings.ffmpeg.fps, 4);
        assert.deepEqual(Object.keys(restored.serialize()).sort(), [
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
        assert.equal(task.serialize().data.submission.settings.ffmpeg.fps, 4);
    });
}

test('video snapshots contain only the local reference and restore without file reads', async (t) => {
    const f = await fixture(t);
    const file = new File(['video bytes'], 'scan.mp4', {
        type: 'video/mp4',
        lastModified: 42,
    });
    const upload = await f.uploads.create('owner', file);

    await f.uploads.setRemote('owner', upload.id, {
        uploadId: 'video',
        uploadUrl: 'https://hud.test/tus/files/video',
    });

    const task = new f.VideoUploadTask({
        id: 'video-task-id',
        createdAt: 123,
        ownerId: 'owner',
        label: 'Upload',
        localUploadId: upload.id,
        uploads: f.uploads,
        onCompleted() {
            assert.fail('Callback must not be restored');
        },
        onUploadAvailable() {
            assert.fail('Callback must not be restored');
        },
    });

    const snapshot = structuredClone(task.serialize());
    snapshot.state.status = 'pausing';
    snapshot.state.progress = { completed: 5, total: file.size };

    const getFile = t.mock.method(f.uploads, 'getFile');
    const restored = f.deserializeTask(snapshot, f.uploads);

    assert.equal(restored.id, task.id);
    assert.notEqual(restored.id, restored.localUploadId);
    assert.equal(restored.localUploadId, upload.id);
    assert.equal(restored.createdAt, 123);
    assert.equal(restored.state.status, 'queued');
    assert.deepEqual(restored.serialize().data, { localUploadId: upload.id });
    assert.equal(getFile.mock.callCount(), 0);
    assert.equal(JSON.stringify(snapshot).includes('onUploadAvailable'), false);
    assert.equal(JSON.stringify(snapshot).includes('uploadUrl'), false);

    assert.deepEqual(await restored.retryOrResume(), {
        uploadId: 'video',
        resumed: true,
    });
    assert.equal(getFile.mock.callCount(), 1);

    const savedFile = await f.uploads.getFile('owner', upload.id);
    assert.equal(await savedFile.text(), 'video bytes');
    assert.equal(savedFile.name, 'scan.mp4');
    assert.equal(savedFile.lastModified, 42);
});

test('unknown and obsolete task formats reject restoration', async (t) => {
    const f = await fixture(t);
    const upload = await f.uploads.create('owner', new File(['x'], 'x.mp4'));
    const task = new f.VideoUploadTask({
        ownerId: 'owner',
        label: 'Upload',
        localUploadId: upload.id,
        uploads: f.uploads,
    });
    const snapshot = task.serialize();

    assert.throws(() => f.deserializeTask({ ...snapshot, type: 'unknown' }, f.uploads), /Unknown/);
    assert.throws(
        () =>
            f.deserializeTask(
                {
                    ...snapshot,
                    data: {
                        uploadUrl: null,
                        uploadState: { uploadId: null, resumed: false },
                    },
                },
                f.uploads,
            ),
        /no local upload ID/,
    );
});

test('a missing file fails execution without preventing task restoration', async (t) => {
    const f = await fixture(t);
    const upload = await f.uploads.create('owner', new File(['x'], 'x.mp4'));
    const task = new f.VideoUploadTask({
        ownerId: 'owner',
        label: 'Upload',
        localUploadId: upload.id,
        uploads: f.uploads,
    });

    f.uploads.files.clear();

    const restored = f.deserializeTask(task.serialize(), f.uploads);
    await restored.retryOrResume();

    assert.equal(restored.state.status, 'failed');
    assert.match(restored.failure.message, /file is missing/);
});
