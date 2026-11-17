import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada, useQueryCache } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';
import { MemoryTasksDatabase } from './helpers/tasksDatabase.mjs';
import { MemoryLocalUploadsRegistry } from './helpers/localUploadsRegistry.mjs';

async function fixture(t, { online = true } = {}) {
    const submissions = [];
    const listeners = new Set();
    let subject = 'test-user';
    const browserWindow = new EventTarget();
    const browserNavigator = { onLine: online };
    const originals = new Map(
        ['window', 'navigator'].map((key) => [
            key,
            Object.getOwnPropertyDescriptor(globalThis, key),
        ]),
    );
    Object.defineProperty(globalThis, 'window', { configurable: true, value: browserWindow });
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: browserNavigator });
    const auth = {
        getAuthSubject: () => subject,
        isAuthenticated: () => subject !== null,
        subscribeAuthChanges(listener) {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
        authFetch(url, init) {
            const gate = deferred();
            submissions.push({ url, init, gate });
            return gate.promise;
        },
    };
    const i18n = { i18n: { global: { t: (key) => key } } };
    const api = await importTypeScript(t, 'src/lib/api.ts', {
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/auth': auth,
    });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': i18n,
        'boot/api': { baseUrl: 'https://hud.test' },
        'src/lib/api': api,
        'src/lib/resumableDownload': { ResumableDownload: {} },
    });
    const tasks = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const idempotency = await importTypeScript(t, 'src/lib/idempotentRequests.ts', {
        'src/lib/api': api,
    });
    const localUploads = await importTypeScript(t, 'src/lib/localUploadsRegistry.ts', {
        'src/lib/api': api,
    });
    const uploads = new MemoryLocalUploadsRegistry();
    const injectedUploads = {
        LocalUploadsRegistry: class {
            constructor() {
                return uploads;
            }
        },
    };
    const reconstructionTasks = await importTypeScript(
        t,
        'src/lib/reconstructionSubmissionTask.ts',
        {
            vue: import.meta.resolve('vue'),
            'src/lib/api': api,
            'src/lib/buildings': buildings,
            'src/lib/idempotentRequests': idempotency,
            'src/lib/networkDependentTasks': tasks,
            'src/lib/localUploadsRegistry': localUploads,
        },
    );
    const authentication = await importTypeScript(t, 'src/composables/useAuthentication.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/auth': auth,
    });
    const connection = await importTypeScript(t, 'src/composables/useOnlineConnection.ts', {
        vue: import.meta.resolve('vue'),
    });
    const database = new MemoryTasksDatabase();
    const queueModule = await importTypeScript(t, 'src/stores/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
        pinia: import.meta.resolve('pinia'),
        'src/composables/useAuthentication': authentication,
        'src/composables/useOnlineConnection': connection,
        'src/lib/networkDependentTasks': tasks,
        'src/lib/localUploadsRegistry': injectedUploads,
        'src/lib/tasksDatabase': {
            TasksDatabase: class {
                constructor() {
                    return database;
                }
            },
        },
        'src/lib/taskRegistry': {
            deserializeTask(snapshot, registry) {
                return reconstructionTasks.ReconstructionSubmissionTask.deserialize(
                    snapshot,
                    registry,
                );
            },
        },
    });
    const { useSubmitReconstructionMutation } = await importTypeScript(
        t,
        'src/mutations/reconstructions.ts',
        {
            vue: import.meta.resolve('vue'),
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'src/i18n/instance': i18n,
            'src/lib/auth': auth,
            'src/lib/api': api,
            'src/lib/buildings': buildings,
            'src/lib/reconstructionSubmissionTask': reconstructionTasks,
            'src/lib/localUploadsRegistry': injectedUploads,
            'src/lib/networkDependentTasks': tasks,
            'src/stores/networkDependentTasks': queueModule,
        },
    );
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada, { mutationOptions: { gcTime: Infinity } });
    const scope = effectScope();
    const queue = app.runWithContext(() => queueModule.useNetworkDependentTasks());
    const cache = app.runWithContext(() => useQueryCache());
    const invalidation = t.mock.method(cache, 'invalidateQueries', () => Promise.resolve());
    t.after(async () => {
        scope.stop();
        await queue.clear();
        disposePinia(pinia);
        setActivePinia(undefined);
        for (const [key, descriptor] of originals) {
            if (descriptor) Object.defineProperty(globalThis, key, descriptor);
            else delete globalThis[key];
        }
    });
    return {
        submissions,
        uploads,
        invalidation,
        queue,
        scope,
        mutation: () => app.runWithContext(() => scope.run(useSubmitReconstructionMutation)),
        connect(connected) {
            browserNavigator.onLine = connected;
            browserWindow.dispatchEvent(new Event(connected ? 'online' : 'offline'));
        },
        setSubject(value) {
            subject = value;
            for (const listener of listeners) listener();
        },
    };
}

function variables(buildingId = 'existing-building') {
    return {
        uploadId: 'stored-upload',
        settings: { ffmpeg: { fps: 4 } },
        ...(buildingId === null
            ? {
                  buildingId: null,
                  building: { name: 'New building', latitude: null, longitude: null },
              }
            : { buildingId }),
    };
}

function respond(submission, body, status = 202) {
    submission.gate.resolve(
        body === null ? new Response(null, { status }) : Response.json(body, { status }),
    );
}

function expectedInvalidations(buildingId) {
    const root = ['buildings', 'test-user'];
    return [
        { key: [...root, 'picker'] },
        { key: [...root, 'list'] },
        { key: [...root, 'locations'] },
        ...(buildingId === null
            ? []
            : [
                  { key: [...root, 'detail', buildingId], exact: true },
                  { key: [...root, 'detail', buildingId, 'reconstructions', 'list'] },
              ]),
    ];
}

function assertInvalidations(f, buildingId) {
    assert.deepEqual(
        f.invalidation.mock.calls.map((call) => call.arguments[0]),
        expectedInvalidations(buildingId),
    );
}

for (const buildingId of ['existing-building', null]) {
    for (const alreadyAssigned of [false, true]) {
        test(`local submission for ${buildingId} returns queued with remote ${alreadyAssigned ? 'present' : 'pending'}`, async (t) => {
            const f = await fixture(t);
            const local = await f.uploads.create('test-user', new File(['video'], 'scan.mp4'));
            const remote = {
                uploadId: 'remote',
                uploadUrl: 'https://hud.test/tus/files/remote',
            };
            if (alreadyAssigned) await f.uploads.setRemote('test-user', local.id, remote);
            const mutation = f.mutation();
            const { uploadId: _uploadId, ...input } = variables(buildingId);
            const outcome = await mutation.mutateAsync({ ...input, localUploadId: local.id });
            assert.equal(outcome.status, 'queued');
            assert.equal(mutation.isLoading.value, false);
            assert.equal(mutation.destinationBuildingId.value, buildingId);
            assert.equal(f.invalidation.mock.callCount(), 0);
            const task = f.queue.get(outcome.taskId);
            assert.ok(task);
            assert.equal(task.serialize().data.submission.localUploadId, local.id);

            await nextTurn();
            if (!alreadyAssigned) {
                assert.equal(f.submissions.length, 0);
                await f.uploads.setRemote('test-user', local.id, remote);
                await nextTurn();
            }
            assert.equal(JSON.parse(f.submissions[0].init.body).upload_id, remote.uploadId);
            respond(f.submissions[0], {
                id: 'reconstruction',
                building_id: buildingId ?? 'created-building',
            });
            await task.waitUntilIdle();
            await nextTurn();
            assert.equal(mutation.data.value, outcome);
            assert.equal(f.queue.pendingCount, 0);
            assertInvalidations(f, buildingId ?? 'created-building');
        });
    }
}

for (const nextSubject of [null, 'another-user']) {
    test(`changing account to ${nextSubject} stops a local dependency wait`, async (t) => {
        const f = await fixture(t);
        const local = await f.uploads.create('test-user', new File(['video'], 'scan.mp4'));
        const { uploadId: _uploadId, ...input } = variables();
        const outcome = await f.mutation().mutateAsync({ ...input, localUploadId: local.id });
        const task = f.queue.get(outcome.taskId);
        await nextTurn();
        f.setSubject(nextSubject);
        await f.queue.initialize();
        await f.uploads.setRemote('test-user', local.id, {
            uploadId: 'remote',
            uploadUrl: 'https://hud.test/tus/files/remote',
        });
        await nextTurn();
        assert.equal(f.submissions.length, 0);
        assert.equal(f.uploads.waiters.size, 0);
        assert.equal(task.state.status, 'queued');
        assert.equal(f.invalidation.mock.callCount(), 0);
    });
}

for (const buildingId of ['existing-building', null]) {
    test(`immediate acceptance returns the ${buildingId === null ? 'new' : 'existing'} building result`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const input = variables(buildingId);
        const pending = mutation.mutateAsync(input);
        await nextTurn();
        assert.equal(mutation.isLoading.value, true);
        assert.equal(f.invalidation.mock.callCount(), 0);
        const request = f.submissions[0];
        const task = f.queue.tasks[0];
        assert.equal(
            request.url,
            buildingId === null
                ? 'https://hud.test/buildings/from-reconstruction/from-upload'
                : 'https://hud.test/buildings/existing-building/reconstructions/from-upload',
        );
        assert.equal(request.init.headers.get('Idempotency-Key'), task.id);
        assert.deepEqual(JSON.parse(request.init.body), {
            upload_id: input.uploadId,
            settings: input.settings,
            ...(buildingId === null ? { building: input.building } : {}),
        });
        const destination = buildingId ?? 'created-building';
        const reconstruction = { id: 'reconstruction-id', building_id: destination };
        respond(
            request,
            buildingId === null
                ? { building: { id: destination }, reconstruction }
                : reconstruction,
        );
        assert.deepEqual(await pending, {
            status: 'completed',
            taskId: task.id,
            result: {
                buildingId: destination,
                reconstructionId: reconstruction.id,
                reconstruction,
                warning: null,
            },
        });
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.errorMessage.value, '');
        assert.equal(f.queue.pendingCount, 0);
        assertInvalidations(f, destination);
    });

    test(`offline success for ${buildingId} is final even after a background scheduling warning`, async (t) => {
        const f = await fixture(t, { online: false });
        const mutation = f.mutation();
        const outcome = await mutation.mutateAsync(variables(buildingId));
        assert.deepEqual(outcome, { status: 'queued', taskId: f.queue.tasks[0].id });
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.destinationBuildingId.value, buildingId);
        assert.equal(mutation.error.value, null);
        assert.equal(f.submissions.length, 0);
        assert.equal(f.invalidation.mock.callCount(), 0);
        const task = f.queue.get(outcome.taskId);
        f.scope.stop();
        f.connect(true);
        await nextTurn();
        respond(
            f.submissions[0],
            {
                detail: {
                    message: 'Scheduling failed',
                    reconstruction_id: 'retained',
                    building_id: buildingId ?? 'created',
                },
            },
            503,
        );
        await task.waitUntilIdle();
        await nextTurn();
        assert.equal(task.state.status, 'completed');
        assert.equal(mutation.data.value, outcome);
        assert.equal(mutation.error.value, null);
        assertInvalidations(f, buildingId ?? 'created');
    });

    test(`scheduling failure for ${buildingId} is an immediate completed result with warning`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const pending = mutation.mutateAsync(variables(buildingId));
        await nextTurn();
        const destination = buildingId ?? 'retained-building';
        respond(
            f.submissions[0],
            {
                detail: {
                    message: 'Scheduling failed',
                    reconstruction_id: 'retained',
                    ...(buildingId === null ? { building_id: destination } : {}),
                },
            },
            503,
        );
        const outcome = await pending;
        assert.equal(outcome.status, 'completed');
        assert.equal(outcome.result.warning, 'Scheduling failed');
        assert.equal(mutation.destinationBuildingId.value, destination);
        assert.equal(mutation.error.value, null);
        assertInvalidations(f, destination);
    });
}

for (const failure of ['network', 'busy', 'unavailable']) {
    test(`${failure} resolves as queued and manual retry uses the same payload and key`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const pending = mutation.mutateAsync(variables());
        await nextTurn();
        if (failure === 'network') f.submissions[0].gate.reject(new TypeError('Connection lost'));
        else
            respond(
                f.submissions[0],
                {
                    detail:
                        failure === 'busy' ? { code: 'idempotency_in_progress' } : 'Unavailable',
                },
                failure === 'busy' ? 409 : 503,
            );
        const outcome = await pending;
        assert.equal(outcome.status, 'queued');
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.error.value, null);
        assert.equal(f.invalidation.mock.callCount(), 0);
        const task = f.queue.get(outcome.taskId);
        f.queue.retry(task.id);
        await nextTurn();
        assert.equal(f.submissions[1].init.body, f.submissions[0].init.body);
        assert.equal(f.submissions[1].init.headers.get('Idempotency-Key'), task.id);
        respond(f.submissions[1], null, 204);
        await task.waitUntilIdle();
        assert.equal(mutation.data.value, outcome);
        assertInvalidations(f, 'existing-building');
    });
}

for (const status of [401, 403, 404, 409, 422]) {
    test(`HTTP ${status} rejects, removes the task, and permits a new user attempt`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        const rejected = assert.rejects(mutation.mutateAsync(variables()), { status });
        await nextTurn();
        const initialKey = f.submissions[0].init.headers.get('Idempotency-Key');
        respond(f.submissions[0], { detail: 'Needs attention' }, status);
        await rejected;
        assert.equal(f.queue.pendingCount, 0);
        assert.equal(mutation.isLoading.value, false);
        assert.equal(mutation.errorMessage.value, 'Needs attention');
        assert.equal(mutation.destinationBuildingId.value, null);
        assert.equal(f.invalidation.mock.callCount(), 0);
        const retry = mutation.mutateAsync(variables());
        await nextTurn();
        assert.notEqual(f.submissions[1].init.headers.get('Idempotency-Key'), initialKey);
        respond(f.submissions[1], { id: 'retry', building_id: 'existing-building' });
        assert.equal((await retry).status, 'completed');
        assertInvalidations(f, 'existing-building');
    });
}

for (const subject of [null, 'another-user']) {
    test(`changed account ${subject} cannot enqueue from an old mutation`, async (t) => {
        const f = await fixture(t);
        const mutation = f.mutation();
        f.setSubject(subject);
        await assert.rejects(mutation.mutateAsync(variables()), { status: 401 });
        assert.equal(f.submissions.length, 0);
    });
}

test('cancellation rejects without displaying a submission error', async (t) => {
    const f = await fixture(t);
    const mutation = f.mutation();
    const rejected = assert.rejects(mutation.mutateAsync(variables()), { name: 'AbortError' });
    await nextTurn();
    const cancellation = f.queue.cancel(f.queue.tasks[0].id);
    respond(f.submissions[0], { id: 'late', building_id: 'existing-building' });
    await cancellation;
    await rejected;
    assert.equal(mutation.isLoading.value, false);
    assert.equal(mutation.errorMessage.value, '');
    assert.equal(mutation.data.value, undefined);
    assert.equal(f.invalidation.mock.callCount(), 0);
});

test('replay without a building ID still invalidates building lists', async (t) => {
    const f = await fixture(t);
    const mutation = f.mutation();
    const pending = mutation.mutateAsync(variables(null));
    await nextTurn();
    respond(f.submissions[0], null, 204);
    assert.equal((await pending).status, 'completed');
    assertInvalidations(f, null);
});

test('cache refresh failure cannot change accepted submission', async (t) => {
    const f = await fixture(t);
    const warning = t.mock.method(console, 'warn', () => {});
    f.invalidation.mock.mockImplementation(() => Promise.reject(new Error('Refresh failed')));
    const mutation = f.mutation();
    const pending = mutation.mutateAsync(variables());
    await nextTurn();
    respond(f.submissions[0], { id: 'accepted', building_id: 'existing-building' });
    assert.equal((await pending).status, 'completed');
    assert.equal(mutation.error.value, null);
    assert.equal(warning.mock.callCount(), 1);
});
