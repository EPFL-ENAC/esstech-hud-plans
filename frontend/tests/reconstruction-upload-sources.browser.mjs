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
            let rejectCreation = false;
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
                    if (path === '/uploads') return route.fulfill({ json: rows.toReversed() });
                    if (path.startsWith('/uploads/')) {
                        const row = rows.find((row) => row.id === path.split('/').pop());
                        assert.ok(row, 'Detail must only open after its row exists');
                        return route.fulfill({ json: row });
                    }
                    if (path === '/buildings') return route.fulfill({ json: [] });
                    assert.ok(path.startsWith('/tus/files/'), `Unexpected request: ${path}`);
                    const headers = { 'Tus-Resumable': '1.0.0' };
                    if (request.method() === 'POST') {
                        creationRequests++;
                        if (rejectCreation)
                            return route.fulfill({ status: 400, body: 'Invalid video' });
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
                    await page.goto(`${origin}/#/reconstructions/from-upload`);
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
                    await page.waitForURL('**/#/reconstructions/from-upload/record');
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
                    await page.getByRole('timer').waitFor();
                    await delay(300);
                    await page.locator('.record-btn-rec').click();
                };
                const detail = async (index) => {
                    const row = rows[index];
                    await page.waitForURL(`**/#/reconstructions/from-upload/${row.id}`);
                    await page
                        .locator('.upload-summary')
                        .getByText(row.filename, { exact: true })
                        .waitFor();
                    await waitFor(() => patches.some((patch) => patch.row.id === row.id));
                    assert.equal(row.status, 'pending');
                    assert.equal(await page.locator('input[type=file], video').count(), 0);
                    const name = page.getByLabel(text.buildings.fields.name, { exact: true });
                    await name.fill(`Preserved ${index}`);
                    patches.find((patch) => patch.row.id === row.id).release();
                    await page
                        .locator('.upload-summary')
                        .getByText(text.uploads.status.uploaded, { exact: false })
                        .waitFor();
                    assert.equal(await name.inputValue(), `Preserved ${index}`);
                    assert.ok(page.url().endsWith(`/reconstructions/from-upload/${row.id}`));
                };

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
                await input().setInputFiles(file(`selected-${locale}-${size}.mp4`));
                await waitFor(() => rows.length === 1);
                await detail(0);
                assert.equal(creationRequests, 1);

                await picker();
                await camera();
                await record();
                await waitFor(() => rows.length === 2);
                assert.match(rows[1].filename, /^capture-.*\.(webm|mp4)$/);
                await detail(1);
                await page.screenshot({ path: join(screenshots, `${locale}-${size}.png`) });
                assert.ok(
                    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                );

                if (locale === 'en' && size === 'desktop') {
                    // A rejected creation can retry the retained file directly.
                    await picker();
                    rejectCreation = true;
                    await input().setInputFiles(file('retry.mp4'));
                    await page.getByText(text.uploads.new.invalidVideo, { exact: true }).waitFor();
                    const failedRequests = creationRequests;
                    rejectCreation = false;
                    await page
                        .getByRole('button', { name: text.common.retry, exact: true })
                        .click();
                    await waitFor(() => rows.length === 3);
                    await detail(2);
                    assert.equal(rows[2].filename, 'retry.mp4');
                    assert.equal(creationRequests, failedRequests + 1);

                    // An aborted handoff retries navigation, without another creation.
                    await picker();
                    await page.evaluate(() => {
                        const router =
                            document.querySelector('#q-app').__vue_app__.config.globalProperties
                                .$router;
                        window.removeUploadGuard = router.beforeEach((to) =>
                            to.name === 'reconstruction-from-upload' ? false : undefined,
                        );
                    });
                    await input().setInputFiles(file('navigation.mp4'));
                    await page
                        .getByText(text.reconstructions.fromUpload.navigationFailed, {
                            exact: true,
                        })
                        .waitFor();
                    const previousRequests = creationRequests;
                    await page.evaluate(() => window.removeUploadGuard());
                    await page
                        .getByRole('button', {
                            name: text.reconstructions.fromUpload.openForm,
                            exact: true,
                        })
                        .click();
                    await detail(3);
                    assert.equal(creationRequests, previousRequests);

                    // Recorder discard and interrupted recording create no upload.
                    await picker();
                    await camera();
                    await page.locator('.record-btn-close').click();
                    await page
                        .getByRole('button', { name: text.capture.record.discard, exact: true })
                        .click();
                    await page.waitForURL('**/#/reconstructions/from-upload');
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
                assert.deepEqual(errors, []);
                console.log(
                    `${locale} ${size}: file/camera early handoff, background completion, preserved form passed`,
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
