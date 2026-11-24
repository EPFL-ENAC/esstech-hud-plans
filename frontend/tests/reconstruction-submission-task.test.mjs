import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { isReadonly, reactive, watchEffect } from 'vue';
import { MemoryLocalUploadsRegistry } from './helpers/localUploadsRegistry.mjs';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    const requests = [];
    const api = await importTypeScript(t, 'src/lib/api.ts', {
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/auth': {
            authFetch(url, init) {
                const gate = deferred();
                requests.push({ url, init, gate });
                return gate.promise;
            },
        },
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: { global: { t: (key) => key } } },
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/api': api,
        'src/lib/resumableDownload': { ResumableDownload: {} },
    });
    const tasks = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const idempotentRequests = await importTypeScript(t, 'src/lib/idempotentRequests.ts', {
        'src/lib/api': api,
    });
    const localUploads = await importTypeScript(t, 'src/lib/localUploadsRegistry.ts', {
        'src/lib/api': api,
    });
    const uploads = new MemoryLocalUploadsRegistry();
    const { ReconstructionSubmissionTask } = await importTypeScript(
        t,
        'src/lib/reconstructionSubmissionTask.ts',
        {
            vue: import.meta.resolve('vue'),
            'src/lib/api': api,
            'src/lib/buildings': buildings,
            'src/lib/networkDependentTasks': tasks,
            'src/lib/idempotentRequests': idempotentRequests,
            'src/lib/localUploadsRegistry': localUploads,
        },
    );
    return {
        requests,
        uploads,
        LocalUploadStorageError: localUploads.LocalUploadStorageError,
        restore: (snapshot) => ReconstructionSubmissionTask.deserialize(snapshot, uploads),
        task: (submission) =>
            new ReconstructionSubmissionTask({
                ownerId: 'owner',
                label: 'Submit reconstruction',
                submission,
                uploads,
            }),
    };
}

function submission(buildingId = 'existing/building') {
    return {
        uploadId: 'upload',
        settings: { ffmpeg: { fps: 4 } },
        ...(buildingId === null
            ? {
                  buildingId: null,
                  building: { name: 'New building', latitude: null, longitude: null },
              }
            : { buildingId }),
    };
}

function localSubmission(localUploadId, buildingId = 'existing/building') {
    const { uploadId: _uploadId, ...input } = submission(buildingId);
    return { ...input, localUploadId };
}

const remote = { uploadId: 'remote', uploadUrl: 'https://hud.test/tus/files/remote' };

for (const buildingId of ['existing/building', null]) {
    for (const alreadyAssigned of [false, true]) {
        test(`local upload for ${buildingId} submits with remote ID assigned ${alreadyAssigned ? 'before' : 'after'} starting`, async (t) => {
            const f = await fixture(t);
            const local = await f.uploads.create('owner', new File(['video'], 'scan.mp4'));
            if (alreadyAssigned) await f.uploads.setRemote('owner', local.id, remote);

            const task = f.task(localSubmission(local.id, buildingId));
            t.after(() => task.cancel());
            const fileReads = t.mock.method(f.uploads, 'getFile');
            const attempt = task.retryOrResume();
            await nextTurn();
            if (!alreadyAssigned) {
                assert.equal(f.requests.length, 0);
                assert.equal(task.state.status, 'running');
                await f.uploads.setRemote('owner', local.id, remote);
                await nextTurn();
            }

            assert.equal(f.requests.length, 1);
            assert.deepEqual(JSON.parse(f.requests[0].init.body), {
                upload_id: remote.uploadId,
                settings: { ffmpeg: { fps: 4 } },
                ...(buildingId === null ? { building: submission(null).building } : {}),
            });
            assert.equal(fileReads.mock.callCount(), 0);
            assert.equal(f.requests[0].init.headers.get('Idempotency-Key'), task.id);

            f.requests[0].gate.reject(new TypeError('Connection lost'));
            await attempt;
            task.requestRetry();
            const retry = task.retryOrResume();
            await nextTurn();
            assert.equal(f.requests[1].init.body, f.requests[0].init.body);
            assert.equal(f.requests[1].init.headers.get('Idempotency-Key'), task.id);
            respond(f.requests[1], null, 204);
            await retry;
            assert.equal(task.state.status, 'completed');
        });
    }
}

test('remote references never read the local registry', async (t) => {
    const f = await fixture(t);
    const read = t.mock.method(f.uploads, 'get');
    const wait = t.mock.method(f.uploads, 'waitForRemote');
    const task = f.task(submission());
    const attempt = task.retryOrResume();
    await nextTurn();
    respond(f.requests[0], null, 204);
    await attempt;
    assert.equal(read.mock.callCount(), 0);
    assert.equal(wait.mock.callCount(), 0);
});

test('cancelling a dependency wait cannot submit later or change the upload', async (t) => {
    const f = await fixture(t);
    const local = await f.uploads.create('owner', new File(['video'], 'scan.mp4'));
    const task = f.task(localSubmission(local.id));
    const attempt = task.retryOrResume();
    await nextTurn();
    await task.cancel();
    await attempt;
    assert.equal(f.uploads.waiters.size, 0);
    await f.uploads.setRemote('owner', local.id, remote);
    await nextTurn();
    assert.equal(task.state.status, 'cancelled');
    assert.equal(f.requests.length, 0);
    assert.deepEqual((await f.uploads.get('owner', local.id)).remote, remote);
});

test('a paused dependency wait resumes by checking the registry again', async (t) => {
    const f = await fixture(t);
    const local = await f.uploads.create('owner', new File(['video'], 'scan.mp4'));
    const task = f.task(localSubmission(local.id));
    const attempt = task.retryOrResume();
    await nextTurn();
    await task.pause();
    await attempt;
    assert.equal(task.state.status, 'queued');
    assert.equal(f.uploads.waiters.size, 0);
    await f.uploads.setRemote('owner', local.id, remote);
    assert.equal(f.requests.length, 0);
    const resumed = task.retryOrResume();
    await nextTurn();
    respond(f.requests[0], null, 204);
    await resumed;
    assert.equal(task.state.status, 'completed');
});

test('a restored waiting submission retains its local reference, input and identity', async (t) => {
    const f = await fixture(t);
    const local = await f.uploads.create('owner', new File(['video'], 'scan.mp4'));
    const input = reactive(localSubmission(local.id, null));
    const task = f.task(input);
    const attempt = task.retryOrResume();
    await nextTurn();
    input.settings.ffmpeg.fps = 99;
    input.building.name = 'Changed';
    const snapshot = structuredClone(task.serialize());
    await task.pause();
    await attempt;

    const restored = f.restore(snapshot);
    t.after(() => restored.cancel());
    assert.equal(restored.id, task.id);
    assert.equal(restored.createdAt, task.createdAt);
    assert.equal(restored.state.status, 'queued');
    assert.deepEqual(restored.serialize().data.submission, localSubmission(local.id, null));
    const resumed = restored.retryOrResume();
    await nextTurn();
    assert.equal(f.requests.length, 0);
    await f.uploads.setRemote('owner', local.id, remote);
    await nextTurn();
    assert.equal(f.requests[0].init.headers.get('Idempotency-Key'), task.id);
    assert.equal(JSON.parse(f.requests[0].init.body).settings.ffmpeg.fps, 4);
    respond(f.requests[0], null, 204);
    await resumed;
    assert.equal(restored.state.status, 'completed');
});

test('a missing local upload fails without sending a request', async (t) => {
    const f = await fixture(t);
    const task = f.task(localSubmission('missing'));
    await task.retryOrResume();
    assert.equal(task.state.status, 'failed');
    assert.equal(task.state.error, 'Local upload is missing.');
    assert.equal(f.requests.length, 0);
});

test('local storage failures block the task and permit manual retry', async (t) => {
    const f = await fixture(t);
    const local = await f.uploads.create('owner', new File(['video'], 'scan.mp4'));
    const task = f.task(localSubmission(local.id));
    const wait = t.mock.method(f.uploads, 'waitForRemote', async () => {
        throw new f.LocalUploadStorageError(new Error('Read failed'));
    });
    await task.retryOrResume();
    assert.equal(task.state.status, 'blocked');
    assert.equal(f.requests.length, 0);
    wait.mock.restore();
    await f.uploads.setRemote('owner', local.id, remote);
    task.requestRetry();
    const retry = task.retryOrResume();
    await nextTurn();
    respond(f.requests[0], null, 204);
    await retry;
    assert.equal(task.state.status, 'completed');
});

function respond(request, body, status = 202) {
    request.gate.resolve(
        body === null ? new Response(null, { status }) : Response.json(body, { status }),
    );
}

for (const buildingId of ['existing/building', null]) {
    const destination = buildingId ?? 'created-building';
    const kind = buildingId === null ? 'new' : 'existing';

    test(`submits to the ${kind} building endpoint and exposes a reactive readonly result`, async (t) => {
        const f = await fixture(t);
        const input = submission(buildingId);
        const task = f.task(input);
        let observed = null;
        t.after(
            watchEffect(() => {
                observed = task.result.value;
            }),
        );
        assert.equal(isReadonly(task.result), true);
        assert.equal(task.result.value, null);
        const attempt = task.retryOrResume();
        await nextTurn();
        const request = f.requests[0];
        assert.equal(
            request.url,
            buildingId === null
                ? 'https://hud.test/buildings/from-reconstruction/from-upload'
                : 'https://hud.test/buildings/existing%2Fbuilding/reconstructions/from-upload',
        );
        assert.equal(request.init.method, 'POST');
        assert.equal(request.init.headers.get('Idempotency-Key'), task.id);
        assert.equal(request.init.headers.get('Content-Type'), 'application/json');
        assert.equal(request.init.signal.aborted, false);
        assert.deepEqual(JSON.parse(request.init.body), {
            upload_id: input.uploadId,
            settings: input.settings,
            ...(buildingId === null ? { building: input.building } : {}),
        });
        const reconstruction = { id: 'reconstruction', building_id: destination };
        respond(
            request,
            buildingId === null
                ? { building: { id: destination }, reconstruction }
                : reconstruction,
        );
        await attempt;
        assert.equal(task.state.status, 'completed');
        assert.deepEqual(task.result.value, {
            buildingId: destination,
            reconstructionId: 'reconstruction',
            reconstruction,
            warning: null,
        });
        assert.equal(observed, task.result.value);
        assert.equal(isReadonly(task.result.value), true);
    });

    test(`retries the same ${kind} building payload and key after an uncertain response`, async (t) => {
        const f = await fixture(t);
        const input = submission(buildingId);
        const task = f.task(input);
        input.settings.ffmpeg.fps = 99;
        input.uploadId = 'different-upload';
        if (buildingId === null) input.building.name = 'Changed name';
        else input.buildingId = 'different-building';
        const attempt = task.retryOrResume();
        await nextTurn();
        f.requests[0].gate.reject(new TypeError('Connection lost'));
        await attempt;
        assert.equal(task.state.status, 'waiting');
        assert.equal(task.state.error, 'errors.connection');
        assert.equal(task.result.value, null);
        task.requestRetry();
        const retry = task.retryOrResume();
        await nextTurn();
        assert.equal(f.requests[1].url, f.requests[0].url);
        assert.equal(f.requests[1].init.body, f.requests[0].init.body);
        assert.equal(JSON.parse(f.requests[1].init.body).settings.ffmpeg.fps, 4);
        assert.equal(JSON.parse(f.requests[1].init.body).upload_id, 'upload');
        if (buildingId === null) {
            assert.equal(JSON.parse(f.requests[1].init.body).building.name, 'New building');
        }
        assert.equal(f.requests[1].init.headers.get('Idempotency-Key'), task.id);
        respond(f.requests[1], null, 204);
        await retry;
        assert.equal(task.state.attempts, 2);
        assert.equal(task.state.status, 'completed');
        assert.equal(task.state.error, null);
        assert.deepEqual(task.result.value, {
            buildingId,
            reconstructionId: null,
            reconstruction: null,
            warning: null,
        });
    });
}

for (const [buildingId, retained, expectedBuildingId] of [
    ['existing', { reconstruction_id: 'retained-reconstruction' }, 'existing'],
    [
        null,
        { building_id: 'retained-building', reconstruction_id: 'retained-reconstruction' },
        'retained-building',
    ],
    [null, { building_id: 'retained-building' }, 'retained-building'],
]) {
    test(`503 with retained IDs completes with a warning: ${JSON.stringify(retained)}`, async (t) => {
        const f = await fixture(t);
        const task = f.task(submission(buildingId));
        const attempt = task.retryOrResume();
        await nextTurn();
        respond(f.requests[0], { detail: { message: 'Scheduling unavailable', ...retained } }, 503);
        await attempt;
        assert.equal(task.state.status, 'completed');
        assert.equal(task.state.error, null);
        assert.deepEqual(task.result.value, {
            buildingId: expectedBuildingId,
            reconstructionId: retained.reconstruction_id ?? null,
            reconstruction: null,
            warning: 'Scheduling unavailable',
        });
        task.requestRetry();
        await task.retryOrResume();
        assert.equal(f.requests.length, 1);
    });
}

for (const [status, detail, expected] of [
    [409, { code: 'idempotency_in_progress' }, 'waiting'],
    [503, 'Database unavailable', 'waiting'],
    [401, 'Session expired', 'blocked'],
    [403, 'Terms required', 'blocked'],
    [409, 'Upload failed', 'failed'],
    [404, 'Missing building', 'failed'],
    [422, 'Invalid settings', 'failed'],
    [422, { message: 'Invalid settings', building_id: 'not-accepted' }, 'failed'],
]) {
    test(`HTTP ${status} ${JSON.stringify(detail)} sets ${expected}`, async (t) => {
        const f = await fixture(t);
        const task = f.task(submission());
        const attempt = task.retryOrResume();
        await nextTurn();
        respond(f.requests[0], { detail }, status);
        await attempt;
        assert.equal(task.state.status, expected);
        assert.equal(task.result.value, null);
        assert.equal(
            task.state.error,
            typeof detail === 'string'
                ? detail
                : (detail.message ?? 'reconstructions.errors.submitFailed'),
        );
        assert.equal(f.requests.length, 1);
    });
}

for (const lateFailure of [false, true]) {
    test(`cancel aborts the request and ignores late ${lateFailure ? 'failure' : 'success'}`, async (t) => {
        const f = await fixture(t);
        const task = f.task(submission());
        const attempt = task.retryOrResume();
        await nextTurn();
        const cancellation = task.cancel();
        assert.equal(f.requests[0].init.signal.aborted, true);
        if (lateFailure) {
            respond(
                f.requests[0],
                { detail: { building_id: 'late', message: 'Late warning' } },
                503,
            );
        } else {
            respond(f.requests[0], { id: 'late', building_id: 'late' });
        }
        await cancellation;
        await attempt;
        assert.equal(task.state.status, 'cancelled');
        assert.equal(task.result.value, null);
        assert.equal(task.state.error, null);
        assert.equal(f.requests.length, 1);
    });
}

test('pause ignores late acceptance and resumes with a fresh signal and the same key', async (t) => {
    const f = await fixture(t);
    const task = f.task(submission());
    const attempt = task.retryOrResume();
    await nextTurn();
    const pause = task.pause();
    respond(f.requests[0], { id: 'late', building_id: 'existing/building' });
    await pause;
    await attempt;
    assert.equal(task.state.status, 'queued');
    assert.equal(task.result.value, null);
    const resume = task.retryOrResume();
    await nextTurn();
    assert.equal(f.requests[0].init.signal.aborted, true);
    assert.equal(f.requests[1].init.signal.aborted, false);
    assert.notEqual(f.requests[1].init.signal, f.requests[0].init.signal);
    assert.equal(f.requests[1].init.headers.get('Idempotency-Key'), task.id);
    respond(f.requests[1], null, 204);
    await resume;
    assert.equal(task.state.status, 'completed');
    assert.equal(task.result.value.buildingId, 'existing/building');
});
