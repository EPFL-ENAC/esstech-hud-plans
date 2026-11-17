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
            const { VideoUploadTask } = await import('/src/lib/videoUploadTask.ts');
            const { ReconstructionSubmissionTask } =
                await import('/src/lib/reconstructionSubmissionTask.ts');
            const app = document.querySelector('#q-app').__vue_app__;
            window.persistenceHarness = {
                queue: app.runWithContext(useNetworkDependentTasks),
                database: new TasksDatabase(),
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
    await offline(true);
    const identity = await page.evaluate(async () => {
        const { queue, VideoUploadTask, ReconstructionSubmissionTask } = window.persistenceHarness;
        const file = new File(['video'], 'scan.mp4', { type: 'video/mp4', lastModified: 42 });
        const video = new VideoUploadTask({ ownerId: 'owner', label: 'Durable video', file });
        const reconstruction = new ReconstructionSubmissionTask({
            ownerId: 'owner',
            label: 'Durable reconstruction',
            submission: {
                buildingId: 'building',
                uploadId: 'stored-upload',
                settings: { ffmpeg: { fps: 4 } },
            },
        });
        const videoResult = await queue.submit(video);
        const reconstructionResult = await queue.submit(reconstruction);
        if (videoResult.status !== 'queued' || reconstructionResult.status !== 'queued')
            throw new Error('Expected durable queued success');
        return {
            videoId: video.id,
            reconstructionId: reconstruction.id,
            createdAt: video.createdAt,
        };
    });
    await reload();
    assert.deepEqual(
        await page.evaluate(async ({ videoId, reconstructionId, createdAt }) => {
            const { queue } = window.persistenceHarness;
            const video = queue.get(videoId);
            return {
                count: queue.pendingCount,
                reconstructed: Boolean(queue.get(reconstructionId)),
                sameDate: video.createdAt === createdAt,
                bytes: await video.file.text(),
                name: video.file.name,
                type: video.file.type,
                lastModified: video.file.lastModified,
            };
        }, identity),
        {
            count: 2,
            reconstructed: true,
            sameDate: true,
            bytes: 'video',
            name: 'scan.mp4',
            type: 'video/mp4',
            lastModified: 42,
        },
    );

    await page.evaluate(() => {
        const { TasksDatabase } = window.persistenceHarness;
        const save = TasksDatabase.prototype.save;
        let held = false;
        TasksDatabase.prototype.save = async function (snapshot) {
            if (!held && snapshot.type === 'video-upload' && snapshot.data.uploadUrl !== null) {
                held = true;
                window.checkpointWaiting = true;
                await new Promise((resolve) => {
                    window.releaseCheckpoint = resolve;
                });
            }
            return save.call(this, snapshot);
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
    const savedUrl = await page.evaluate(async () => {
        const rows = await window.persistenceHarness.database.list('owner');
        return rows.find(({ type }) => type === 'video-upload').data.uploadUrl;
    });
    assert.equal(savedUrl, `${origin}/persist-api/tus/files/video`);
    await reload();
    assert.equal(
        await page.evaluate(
            (id) => window.persistenceHarness.queue.get(id).serialize().snapshot.data.uploadUrl,
            identity.videoId,
        ),
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
    assert.equal(
        await page.evaluate(async (id) => {
            try {
                await window.persistenceHarness.database.files('owner', id).get('video');
                return false;
            } catch {
                return true;
            }
        }, identity.videoId),
        true,
    );
    console.log(
        'Reload: File metadata/bytes, task identities, exact URL, commit-before-PATCH and attachment cleanup passed',
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
    const accountTaskId = await page.evaluate(async () => {
        const { queue, VideoUploadTask } = window.persistenceHarness;
        const task = new VideoUploadTask({
            ownerId: 'owner',
            label: 'Account video',
            file: new File(['video'], 'owner.mp4'),
        });
        await queue.submit(task);
        return task.id;
    });
    await page.evaluate(async (accessToken) => {
        const { setAccessToken } = await import('/src/lib/auth.ts');
        setAccessToken(accessToken);
        await window.persistenceHarness.queue.initialize();
    }, token('other'));
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
        serialized.snapshot.type = 'retired-task-type';
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
    assert.equal(
        await page.evaluate(async () =>
            (await indexedDB.databases()).some(({ name }) => name === 'hud-network-tasks'),
        ),
        false,
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
