import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://127.0.0.1:9050';
const token = (owner) =>
    `test.${Buffer.from(JSON.stringify({ sub: owner, exp: 4_000_000_000 })).toString('base64url')}.test`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ serviceWorkers: 'block' });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
const requests = [];
let offset = 0;
let interrupted = false;
let creations = 0;
let replayKey = null;
let replayAttempts = 0;

try {
    await context.addInitScript((accessToken) => {
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('hud-language', 'en');
        Object.defineProperty(navigator, 'onLine', {
            configurable: true,
            get: () => sessionStorage.getItem('test-offline') !== '1',
        });
    }, token('owner'));
    await context.route('**/env.js', (route) =>
        route.fulfill({
            contentType: 'application/javascript',
            body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/persist-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
        }),
    );
    await context.route('**/persist-api/**', async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname.replace('/persist-api', '');
        requests.push({
            method: request.method(),
            path,
            key: request.headers()['idempotency-key'],
        });
        if (path === '/user/me')
            return route.fulfill({ json: { id: 'owner', terms_accepted: true } });
        if (path.endsWith('/reconstructions/from-upload')) {
            const body = request.postDataJSON();
            if (body.upload_id === 'replay-upload') {
                replayAttempts++;
                const key = request.headers()['idempotency-key'];
                if (replayKey === null) {
                    replayKey = key;
                    return route.abort('failed');
                }
                assert.equal(key, replayKey);
                return route.fulfill({ status: 204 });
            }
            return route.fulfill({
                status: 202,
                json: { id: 'reconstruction', building_id: 'building' },
            });
        }
        if (path === '/tus/files/' && request.method() === 'POST') {
            creations++;
            return route.fulfill({
                status: 201,
                headers: {
                    Location: `${origin}/persist-api/tus/files/video`,
                    'Tus-Resumable': '1.0.0',
                },
            });
        }
        if (path === '/tus/files/video') {
            if (request.method() === 'HEAD')
                return route.fulfill({
                    status: 200,
                    headers: {
                        'Tus-Resumable': '1.0.0',
                        'Upload-Offset': String(offset),
                        'Upload-Length': '5',
                    },
                });
            assert.equal(request.method(), 'PATCH');
            assert.equal(request.headers()['upload-offset'], String(offset));
            if (!interrupted) {
                interrupted = true;
                offset = 2;
                await page.evaluate(() => {
                    sessionStorage.setItem('test-offline', '1');
                    window.dispatchEvent(new Event('offline'));
                });
                await route.abort('failed').catch(() => undefined);
                return;
            }
            assert.equal(request.postDataBuffer().toString(), 'deo');
            offset = 5;
            return route.fulfill({
                status: 204,
                headers: { 'Tus-Resumable': '1.0.0', 'Upload-Offset': '5' },
            });
        }
        return route.fulfill({ json: { items: [], total: 0 } });
    });

    async function harness() {
        await page.waitForFunction(() => document.querySelector('#q-app')?.__vue_app__);
        await page.evaluate(async () => {
            const { useNetworkDependentTasks } =
                await import('/src/stores/networkDependentTasks.ts');
            const { TasksDatabase } = await import('/src/lib/tasksDatabase.ts');
            const { LocalUploadsRegistry } = await import('/src/lib/localUploadsRegistry.ts');
            const { VideoUploadTask } = await import('/src/lib/videoUploadTask.ts');
            const { ReconstructionSubmissionTask } =
                await import('/src/lib/reconstructionSubmissionTask.ts');
            const app = document.querySelector('#q-app').__vue_app__;
            window.persistenceHarness = {
                queue: app.runWithContext(useNetworkDependentTasks),
                database: new TasksDatabase(),
                uploads: new LocalUploadsRegistry(),
                LocalUploadsRegistry,
                TasksDatabase,
                VideoUploadTask,
                ReconstructionSubmissionTask,
            };
            await window.persistenceHarness.queue.initialize();
        });
    }
    async function offline(value) {
        await page.evaluate((offline) => {
            sessionStorage.setItem('test-offline', offline ? '1' : '0');
            window.dispatchEvent(new Event(offline ? 'offline' : 'online'));
        }, value);
    }
    async function reload() {
        await page.reload();
        await harness();
    }

    await page.goto(`${origin}/#/more/tasks`);
    await harness();
    await page.evaluate(async () => {
        const { uploads } = window.persistenceHarness;
        try {
            await uploads.create('validation-owner', new File([], 'empty.mp4'));
            throw new Error('Empty registration unexpectedly succeeded');
        } catch (error) {
            if (error.status !== 400) throw error;
        }

        const originalAdd = IDBObjectStore.prototype.add;
        IDBObjectStore.prototype.add = function (...args) {
            if (this.name === 'files') {
                throw new DOMException('Full', 'QuotaExceededError');
            }
            return originalAdd.apply(this, args);
        };
        try {
            try {
                await uploads.create('validation-owner', new File(['video'], 'quota.mp4'));
                throw new Error('Quota failure unexpectedly succeeded');
            } catch (error) {
                if (error.cause?.name !== 'QuotaExceededError') throw error;
            }
        } finally {
            IDBObjectStore.prototype.add = originalAdd;
        }
        if ((await uploads.list('validation-owner')).length !== 0) {
            throw new Error('Failed registration left partial metadata');
        }
    });
    await offline(true);
    const identity = await page.evaluate(async () => {
        const { queue, ReconstructionSubmissionTask } = window.persistenceHarness;
        const { useScheduleVideoUploadMutation } = await import('/src/mutations/uploads.ts');
        const app = document.querySelector('#q-app').__vue_app__;
        const mutation = app.runWithContext(useScheduleVideoUploadMutation);
        const file = new File(['video'], 'scan.mp4', { type: 'video/mp4', lastModified: 42 });
        const prepared = await mutation.mutateAsync({ file });
        const video = queue.get(prepared.taskId);
        if (!video) throw new Error('Prepared upload task is missing from the queue');
        const reconstruction = new ReconstructionSubmissionTask({
            ownerId: 'owner',
            label: 'Durable reconstruction',
            submission: {
                buildingId: 'building',
                uploadId: 'stored-upload',
                settings: { ffmpeg: { fps: 4 } },
            },
        });
        const reconstructionResult = await queue.submit(reconstruction);
        if (reconstructionResult.status !== 'queued') {
            throw new Error('Expected a durable queued reconstruction');
        }
        return {
            videoId: prepared.taskId,
            localUploadId: prepared.localUploadId,
            reconstructionId: reconstruction.id,
            createdAt: video.createdAt,
        };
    });
    await reload();
    assert.deepEqual(
        await page.evaluate(async ({ videoId, localUploadId, reconstructionId, createdAt }) => {
            const { queue, uploads } = window.persistenceHarness;
            const video = queue.get(videoId);
            const file = await uploads.getFile('owner', localUploadId);
            return {
                count: queue.pendingCount,
                reconstructed: Boolean(queue.get(reconstructionId)),
                sameDate: video.createdAt === createdAt,
                sameLocalId: video.localUploadId === localUploadId,
                independentIds: video.id !== localUploadId,
                bytes: await file.text(),
                name: file.name,
                type: file.type,
                lastModified: file.lastModified,
            };
        }, identity),
        {
            count: 2,
            reconstructed: true,
            sameDate: true,
            sameLocalId: true,
            independentIds: true,
            bytes: 'video',
            name: 'scan.mp4',
            type: 'video/mp4',
            lastModified: 42,
        },
    );

    await page.evaluate(() => {
        const { LocalUploadsRegistry } = window.persistenceHarness;
        const setRemote = LocalUploadsRegistry.prototype.setRemote;
        const put = IDBObjectStore.prototype.put;
        const add = IDBObjectStore.prototype.add;
        let held = false;
        window.registryFileWrites = 0;
        IDBObjectStore.prototype.put = function (...args) {
            if (this.name === 'files') window.registryFileWrites++;
            return put.apply(this, args);
        };
        IDBObjectStore.prototype.add = function (...args) {
            if (this.name === 'files') window.registryFileWrites++;
            return add.apply(this, args);
        };
        LocalUploadsRegistry.prototype.setRemote = async function (...args) {
            if (!held) {
                held = true;
                window.checkpointWaiting = true;
                await new Promise((resolve) => {
                    window.releaseCheckpoint = resolve;
                });
            }
            return setRemote.apply(this, args);
        };
    });
    await offline(false);
    await page.waitForFunction(() => window.checkpointWaiting === true);
    assert.equal(requests.filter(({ method }) => method === 'PATCH').length, 0);
    await page.waitForFunction(
        (id) => !window.persistenceHarness.queue.get(id),
        identity.reconstructionId,
    );
    assert.equal(
        requests.find(({ key }) => key === identity.reconstructionId).key,
        identity.reconstructionId,
    );
    await page.evaluate(() => window.releaseCheckpoint());
    await page.waitForFunction(
        (id) => window.persistenceHarness.queue.get(id)?.state.status === 'queued',
        identity.videoId,
    );
    const savedUrl = await page.evaluate(async (localUploadId) => {
        const record = await window.persistenceHarness.uploads.get('owner', localUploadId);
        return record.remote.uploadUrl;
    }, identity.localUploadId);
    assert.equal(savedUrl, `${origin}/persist-api/tus/files/video`);
    assert.equal(await page.evaluate(() => window.registryFileWrites), 0);
    await reload();
    assert.equal(
        await page.evaluate(async (localUploadId) => {
            const record = await window.persistenceHarness.uploads.get('owner', localUploadId);
            return record.remote.uploadUrl;
        }, identity.localUploadId),
        savedUrl,
    );
    await offline(false);
    await page.waitForFunction(() => window.persistenceHarness.queue.pendingCount === 0);
    assert.equal(creations, 1);
    assert.equal(offset, 5);
    assert.equal(requests.filter(({ method }) => method === 'HEAD').length, 1);
    assert.equal(
        await page.evaluate(
            async () => (await window.persistenceHarness.database.list('owner')).length,
        ),
        0,
    );
    assert.deepEqual(
        await page.evaluate(async (localUploadId) => {
            const { uploads } = window.persistenceHarness;
            const record = await uploads.get('owner', localUploadId);
            const file = await uploads.getFile('owner', localUploadId);
            return { remote: record.remote, bytes: await file.text() };
        }, identity.localUploadId),
        {
            remote: { uploadId: 'video', uploadUrl: savedUrl },
            bytes: 'video',
        },
    );

    const patchCount = requests.filter(({ method }) => method === 'PATCH').length;
    const headCount = requests.filter(({ method }) => method === 'HEAD').length;
    const replacement = await page.evaluate(async (localUploadId) => {
        const { queue, uploads, VideoUploadTask } = window.persistenceHarness;
        const task = new VideoUploadTask({
            ownerId: 'owner',
            label: 'Already transferred video',
            localUploadId,
            uploads,
        });
        const outcome = await queue.submit(task);
        return { taskId: task.id, outcome };
    }, identity.localUploadId);

    assert.notEqual(replacement.taskId, identity.videoId);
    assert.equal(replacement.outcome.status, 'completed');
    assert.deepEqual(replacement.outcome.result, { uploadId: 'video', resumed: true });
    assert.equal(creations, 1);
    assert.equal(requests.filter(({ method }) => method === 'PATCH').length, patchCount);
    assert.equal(requests.filter(({ method }) => method === 'HEAD').length, headCount + 1);

    await page.evaluate(async (localUploadId) => {
        const { uploads } = window.persistenceHarness;
        const remote = (await uploads.get('owner', localUploadId)).remote;
        await uploads.setRemote('owner', localUploadId, remote);
        try {
            await uploads.setRemote('owner', localUploadId, {
                uploadId: 'replacement',
                uploadUrl: 'https://hud.test/tus/files/replacement',
            });
            throw new Error('Remote replacement unexpectedly succeeded');
        } catch (error) {
            if (!error.cause?.message.includes('different remote upload')) throw error;
        }
        try {
            await uploads.setRemote('owner', 'missing', remote);
            throw new Error('Remote write recreated a missing upload');
        } catch (error) {
            if (!error.cause?.message.includes('Local upload is missing')) throw error;
        }
        const saved = await uploads.get('owner', localUploadId);
        if (
            saved.remote.uploadId !== remote.uploadId ||
            saved.remote.uploadUrl !== remote.uploadUrl
        ) {
            throw new Error('Rejected write changed the remote reference');
        }
    }, identity.localUploadId);
    console.log(
        'Registry: reload, retained files, metadata-only checkpoints, and completed-upload reuse passed',
    );

    const replayId = await page.evaluate(async () => {
        const { queue, ReconstructionSubmissionTask } = window.persistenceHarness;
        const task = new ReconstructionSubmissionTask({
            ownerId: 'owner',
            label: 'Replay',
            submission: {
                buildingId: 'building',
                uploadId: 'replay-upload',
                settings: { ffmpeg: { fps: 4 } },
            },
        });
        const outcome = await queue.submit(task);
        if (outcome.status !== 'queued') throw new Error('Network error should hand off');
        return task.id;
    });
    assert.equal(replayAttempts, 1);
    await reload();
    await page.waitForFunction(() => window.persistenceHarness.queue.pendingCount === 0);
    assert.equal(replayAttempts, 2);
    assert.equal(replayKey, replayId);
    console.log(
        'Reconstruction: uncertain request replays the original idempotency key after reload',
    );

    await offline(true);
    await page.evaluate(async () => {
        const { queue, uploads, TasksDatabase, VideoUploadTask } = window.persistenceHarness;
        const upload = await uploads.create('owner', new File(['video'], 'retained.mp4'));
        const task = new VideoUploadTask({
            ownerId: 'owner',
            label: 'Admission failure',
            localUploadId: upload.id,
            uploads,
        });
        const create = TasksDatabase.prototype.create;
        TasksDatabase.prototype.create = async function () {
            throw new Error('Task admission failed');
        };
        try {
            try {
                await queue.submit(task);
                throw new Error('Admission unexpectedly succeeded');
            } catch (error) {
                if (error.cause?.message !== 'Task admission failed') throw error;
            }
        } finally {
            TasksDatabase.prototype.create = create;
        }
        const record = await uploads.get('owner', upload.id);
        const file = await uploads.getFile('owner', upload.id);
        if (record.id !== upload.id || (await file.text()) !== 'video') {
            throw new Error('Failed task admission lost the registered upload');
        }
        if (queue.get(task.id)) throw new Error('Failed admission left an active task');
    });

    const accountUpload = await page.evaluate(async () => {
        const { queue, uploads, VideoUploadTask } = window.persistenceHarness;
        const upload = await uploads.create('owner', new File(['video'], 'owner.mp4'));
        const task = new VideoUploadTask({
            ownerId: 'owner',
            label: 'Account video',
            localUploadId: upload.id,
            uploads,
        });
        await queue.submit(task);
        return { taskId: task.id, localUploadId: upload.id };
    });
    const accountTaskId = accountUpload.taskId;
    await page.evaluate(async (accessToken) => {
        const { setAccessToken } = await import('/src/lib/auth.ts');
        setAccessToken(accessToken);
        await window.persistenceHarness.queue.initialize();
    }, token('other'));
    assert.deepEqual(
        await page.evaluate(() => window.persistenceHarness.uploads.list('other')),
        [],
    );
    assert.equal(
        await page.evaluate(async (localUploadId) => {
            try {
                await window.persistenceHarness.uploads.get('other', localUploadId);
                return false;
            } catch {
                return true;
            }
        }, accountUpload.localUploadId),
        true,
    );
    assert.equal(await page.evaluate(() => window.persistenceHarness.queue.pendingCount), 0);
    assert.equal(
        await page.evaluate(
            async () => (await window.persistenceHarness.database.list('owner')).length,
        ),
        1,
    );
    await page.evaluate(async (accessToken) => {
        const { setAccessToken } = await import('/src/lib/auth.ts');
        setAccessToken(accessToken);
        await window.persistenceHarness.queue.initialize();
    }, token('owner'));
    assert.equal(
        await page.evaluate(
            (id) => Boolean(window.persistenceHarness.queue.get(id)),
            accountTaskId,
        ),
        true,
    );
    await page.evaluate(async (id) => {
        await window.persistenceHarness.queue.cancel(id);
    }, accountTaskId);
    assert.equal(
        await page.evaluate(async (localUploadId) => {
            const file = await window.persistenceHarness.uploads.getFile('owner', localUploadId);
            return file.text();
        }, accountUpload.localUploadId),
        'video',
    );
    assert.equal(
        await page.evaluate(
            async () => (await window.persistenceHarness.database.list('owner')).length,
        ),
        0,
    );

    await page.evaluate(async () => {
        const { database, ReconstructionSubmissionTask } = window.persistenceHarness;
        const serialized = new ReconstructionSubmissionTask({
            ownerId: 'owner',
            label: 'Unknown',
            submission: {
                buildingId: 'building',
                uploadId: 'stored-upload',
                settings: { ffmpeg: { fps: 4 } },
            },
        }).serialize();
        serialized.type = 'retired-task-type';
        await database.create(serialized);
    });
    await reload();
    assert.match(
        await page.evaluate(() => window.persistenceHarness.queue.storageError),
        /Unknown saved task type/,
    );
    assert.equal(
        await page.evaluate(
            async () => (await window.persistenceHarness.database.list('owner')).length,
        ),
        1,
    );
    await page.evaluate(async () => {
        await window.persistenceHarness.queue.clearSaved();
        const { clearLocalData } = await import('/src/lib/auth.ts');
        await clearLocalData();
    });
    assert.deepEqual(
        await page.evaluate(async () =>
            (await indexedDB.databases())
                .map(({ name }) => name)
                .filter((name) => ['hud-network-tasks', 'hud-local-uploads'].includes(name)),
        ),
        [],
    );
    assert.deepEqual(errors, []);
    console.log(
        'Accounts, unknown-record retention, cancellation, and clearing local task data passed',
    );
} catch (error) {
    console.error({
        url: page.url(),
        errors,
        requests,
        body: await page.locator('body').innerText(),
    });
    throw error;
} finally {
    await context.close();
    await browser.close();
}
