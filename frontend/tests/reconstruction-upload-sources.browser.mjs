import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

// node tests/reconstruction-upload-sources.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9050';
const screenshots = join(tmpdir(), 'hud-reconstruction-upload-sources');
await mkdir(screenshots, { recursive: true });
const token = `test.${Buffer.from(JSON.stringify({ sub: 'sources-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for upload');
        await delay(20);
    }
}
const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
});
try {
    for (const locale of ['en', 'fr', 'es']) {
        const source = await readFile(
            new URL(`../src/i18n/${locale === 'en' ? 'en-US' : locale}/index.ts`, import.meta.url),
            'utf8',
        );
        const { outputText } = ts.transpileModule(source, {
            compilerOptions: { module: ts.ModuleKind.ESNext },
        });
        const { default: text } = await import(
            `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
        );
        for (const [size, viewport] of Object.entries({
            mobile: { width: 390, height: 844 },
            desktop: { width: 1440, height: 1000 },
        })) {
            const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
            const rows = [];
            const patches = [];
            const submissions = [];
            const existingBuilding = {
                id: 'existing',
                user_id: 'sources-owner',
                name: 'Existing building',
                address: null,
                latitude: null,
                longitude: null,
                created_at: '2026-10-14T10:00:00Z',
                updated_at: '2026-10-14T10:00:00Z',
            };
            const query = '?buildingId=existing';
            const uploadDetailRequests = [];
            let creationRequests = 0;
            try {
                await context.addInitScript(
                    ({ token, locale }) => {
                        localStorage.setItem('access_token', token);
                        localStorage.setItem('hud-language', locale);
                        localStorage.setItem('hud-hide-video-tips', 'true');
                    },
                    { token, locale },
                );
                await context.route('**/env.js', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/sources-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                await context.route('**/sources-api/**', async (route) => {
                    const request = route.request();
                    const path = new URL(request.url()).pathname.replace('/sources-api', '');
                    assert.equal(request.headers().authorization, `Bearer ${token}`);
                    if (path === '/user/me')
                        return route.fulfill({
                            json: { id: 'sources-owner', terms_accepted: true },
                        });
                    if (path === '/uploads')
                        return route.fulfill({
                            json: { items: rows.toReversed(), total: rows.length },
                        });
                    if (path.startsWith('/uploads/')) {
                        const id = path.split('/').at(-1);
                        uploadDetailRequests.push(id);
                        const row = rows.find((row) => row.id === id);
                        return row
                            ? route.fulfill({ json: row })
                            : route.fulfill({ status: 404, json: { detail: 'Upload not found' } });
                    }
                    if (path === '/buildings/from-reconstruction/from-upload') {
                        submissions.push(request.postDataJSON());
                        return route.fulfill({
                            status: 202,
                            json: { building_id: 'created', id: 'reconstruction' },
                        });
                    }
                    if (path.startsWith('/buildings/')) {
                        return path === '/buildings/existing'
                            ? route.fulfill({
                                  json: existingBuilding,
                              })
                            : route.fulfill({
                                  status: 404,
                                  json: { detail: 'Building not found' },
                              });
                    }
                    if (path === '/buildings')
                        return route.fulfill({
                            json: {
                                items: [{ ...existingBuilding, latest_reconstruction: null }],
                                total: 1,
                            },
                        });
                    assert.ok(path.startsWith('/tus/files/'), `Unexpected request: ${path}`);
                    const headers = { 'Tus-Resumable': '1.0.0' };
                    if (request.method() === 'POST') {
                        creationRequests++;
                        const metadata = Object.fromEntries(
                            request
                                .headers()
                                ['upload-metadata'].split(',')
                                .map((part) => {
                                    const [key, value] = part.trim().split(' ');
                                    return [key, Buffer.from(value, 'base64').toString()];
                                }),
                        );
                        const id = String(rows.length + 1).padStart(32, '0');
                        rows.push({
                            id,
                            user_id: 'sources-owner',
                            name: 'TODO',
                            description: '',
                            filename: metadata.filename,
                            size_bytes: Number(request.headers()['upload-length']),
                            uploaded_bytes: 0,
                            status: 'pending',
                            created_at: new Date().toISOString(),
                            uploaded_at: null,
                        });
                        return route.fulfill({
                            status: 201,
                            headers: {
                                ...headers,
                                Location: `${origin}/sources-api/tus/files/${id}`,
                            },
                        });
                    }
                    const row = rows.find((row) => row.id === path.split('/').pop());
                    assert.ok(row);
                    if (request.method() === 'HEAD')
                        return route.fulfill({
                            status: 200,
                            headers: {
                                ...headers,
                                'Upload-Length': String(row.size_bytes),
                                'Upload-Offset': '0',
                            },
                        });
                    assert.equal(request.method(), 'PATCH');
                    await new Promise((resolve) => patches.push({ row, release: resolve }));
                    row.status = 'uploaded';
                    row.uploaded_bytes = row.size_bytes;
                    row.uploaded_at = new Date().toISOString();
                    return route.fulfill({
                        status: 204,
                        headers: { ...headers, 'Upload-Offset': String(row.size_bytes) },
                    });
                });
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                const picker = async () => {
                    await page.goto(`${origin}/#/reconstructions/from-upload${query}`);
                    await page
                        .getByRole('link', { name: text.capture.video.takeVideo, exact: true })
                        .waitFor();
                };
                const input = () => page.locator('input[type=file]');
                const file = (name) => ({
                    name,
                    mimeType: 'video/mp4',
                    buffer: Buffer.alloc(1024, 7),
                });
                const camera = async () => {
                    await page
                        .getByRole('link', { name: text.capture.video.takeVideo, exact: true })
                        .click();
                    await page.waitForURL(`**/#/reconstructions/from-upload/record${query}`);
                    await page.waitForFunction(() => {
                        const button = document.querySelector('.record-btn-rec');
                        return button && !button.disabled;
                    });
                    assert.equal(
                        await page.locator('input[type=file], .upload-summary').count(),
                        0,
                    );
                };
                const record = async () => {
                    await page.locator('.record-btn-rec').click();
                    await page.getByRole('timer').getByText('00:01', { exact: true }).waitFor();
                    await page.locator('.record-btn-rec').click();
                };
                const localForm = page.locator('.reconstruction-form');
                const summary = page.locator('.upload-summary');
                const setOnline = (online) =>
                    page.evaluate((online) => {
                        Object.defineProperty(navigator, 'onLine', {
                            configurable: true,
                            value: online,
                        });
                        window.dispatchEvent(new Event(online ? 'online' : 'offline'));
                    }, online);
                async function readLocalBackup() {
                    try {
                        await page.waitForURL(
                            (url) => url.hash.startsWith('#/reconstructions/from-upload/local/'),
                            { timeout: 10_000 },
                        );
                    } catch (error) {
                        const alerts = await page.getByRole('alert').allTextContents();
                        throw new Error(
                            `Local form did not open: ${[...alerts, ...errors].join(' | ')}`,
                            { cause: error },
                        );
                    }
                    await localForm.waitFor();
                    assert.equal(await page.locator('input[type=file], video').count(), 0);
                    assert.equal(
                        await page
                            .getByRole('button', { name: text.uploads.refresh, exact: true })
                            .count(),
                        0,
                    );

                    const [path, queryString] = new URL(page.url()).hash.split('?');
                    assert.equal(new URLSearchParams(queryString).get('buildingId'), 'existing');
                    const localUploadId = path.split('/').at(-1);
                    const backup = await page.evaluate(async (id) => {
                        const { LocalUploadsRegistry } =
                            await import('/src/lib/localUploadsRegistry.ts');
                        const uploads = new LocalUploadsRegistry();
                        const record = await uploads.get('sources-owner', id);
                        const file = await uploads.getFile('sources-owner', id);
                        return { name: file.name, size: file.size, remote: record.remote };
                    }, localUploadId);
                    await summary.getByText(backup.name, { exact: true }).waitFor();
                    await summary.getByText(text.tasks.status.queued, { exact: true }).waitFor();
                    return backup;
                }
                async function finishTransfer(index) {
                    await waitFor(() => patches.some(({ row }) => row === rows[index]));
                    patches.find(({ row }) => row === rows[index]).release();
                    await waitFor(() => rows[index].status === 'uploaded');
                }
                async function selectNewBuilding(buildingName) {
                    const buildingPicker = localForm.locator('.q-select').first();
                    await buildingPicker.getByText('Existing building', { exact: true }).waitFor();
                    await buildingPicker.click();
                    await page
                        .getByRole('option')
                        .getByText(text.buildings.picker.createNew, { exact: true })
                        .click();
                    const name = page.getByLabel(text.buildings.fields.name, { exact: true });
                    await name.fill(buildingName);
                    return name;
                }

                await picker();
                await input().setInputFiles([]);
                assert.equal(creationRequests, 0);
                await input().setInputFiles({
                    name: 'empty.mp4',
                    mimeType: 'video/mp4',
                    buffer: Buffer.alloc(0),
                });
                await page.getByText(text.uploads.new.emptyFile, { exact: true }).waitFor();
                assert.equal(creationRequests, 0);
                await setOnline(false);
                const filename = `selected-${locale}-${size}.mp4`;
                await input().setInputFiles(file(filename));
                assert.deepEqual(await readLocalBackup(), {
                    name: filename,
                    size: 1024,
                    remote: null,
                });
                assert.equal(creationRequests, 0);
                assert.deepEqual(uploadDetailRequests, []);

                const submitOffline = locale === 'en' && size === 'desktop';
                if (submitOffline) {
                    await selectNewBuilding('Offline building');
                    await page
                        .getByRole('button', { name: text.capture.startProcessing, exact: true })
                        .click();
                    await page.waitForURL('**/#/library');
                    assert.deepEqual(submissions, []);
                    assert.equal(creationRequests, 0);
                }
                await setOnline(true);
                if (submitOffline) {
                    await waitFor(() => submissions.length === 1);
                    assert.equal(submissions[0].upload_id, rows[0].id);
                    assert.equal(submissions[0].building.name, 'Offline building');
                }
                await finishTransfer(0);
                assert.equal(creationRequests, 1);

                await picker();
                await camera();
                await setOnline(false);
                await record();

                const recording = await readLocalBackup();
                assert.match(recording.name, /^capture-.*\.(webm|mp4)$/);
                assert.ok(recording.size > 0);
                assert.equal(recording.remote, null);
                assert.equal(creationRequests, 1);
                const name = await selectNewBuilding('Preserved building');
                const localUrl = page.url();

                await setOnline(true);
                await summary.getByText(text.uploads.status.pending, { exact: true }).waitFor();
                await summary.getByRole('progressbar').waitFor();
                await finishTransfer(1);
                await summary.getByText(text.uploads.status.uploaded, { exact: true }).waitFor();
                assert.equal(creationRequests, 2);
                assert.equal(page.url(), localUrl);
                assert.equal(await name.inputValue(), 'Preserved building');
                assert.equal(await summary.count(), 1);
                assert.ok(uploadDetailRequests.includes(rows[1].id));
                await page.screenshot({ path: join(screenshots, `${locale}-${size}.png`) });
                assert.ok(
                    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                );

                if (locale === 'en' && size === 'desktop') {
                    await picker();
                    await setOnline(false);
                    await page.evaluate(() => {
                        const router =
                            document.querySelector('#q-app').__vue_app__.config.globalProperties
                                .$router;
                        window.removeUploadGuard = router.beforeEach((to) =>
                            to.name === 'reconstruction-from-local-upload' ? false : undefined,
                        );
                    });
                    await input().setInputFiles(file('navigation.mp4'));
                    await page
                        .getByText(text.reconstructions.fromUpload.navigationFailed, {
                            exact: true,
                        })
                        .waitFor();
                    await page.evaluate(() => window.removeUploadGuard());
                    await page
                        .getByRole('button', {
                            name: text.reconstructions.fromUpload.openForm,
                            exact: true,
                        })
                        .click();
                    assert.equal((await readLocalBackup()).name, 'navigation.mp4');
                    assert.equal(creationRequests, 2);
                    await setOnline(true);
                    await finishTransfer(2);
                    const previousRequests = 3;
                    assert.equal(creationRequests, previousRequests);

                    // Recorder discard and interrupted recording create no upload.
                    await picker();
                    await camera();
                    await page.locator('.record-btn-close').click();
                    await page
                        .getByRole('button', { name: text.capture.record.discard, exact: true })
                        .click();
                    await page.waitForURL(`**/#/reconstructions/from-upload${query}`);
                    assert.equal(creationRequests, previousRequests);
                    await camera();
                    await page.locator('.record-btn-rec').click();
                    await page.getByRole('timer').waitFor();
                    await page.evaluate(() =>
                        document
                            .querySelector('video')
                            .srcObject.getVideoTracks()[0]
                            .dispatchEvent(new Event('ended')),
                    );
                    await page.getByRole('alert').first().waitFor();
                    assert.equal(creationRequests, previousRequests);
                }
                assert.ok(uploadDetailRequests.every((id) => rows.some((row) => row.id === id)));
                assert.deepEqual(errors, []);
                console.log(
                    `${locale} ${size}: local file/camera handoff, summary progress, preserved form passed`,
                );
            } finally {
                patches.forEach((patch) => patch.release());
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
