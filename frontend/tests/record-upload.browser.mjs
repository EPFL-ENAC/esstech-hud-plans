import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/record-upload.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9050';
const screenshots = join(tmpdir(), 'hud-record-upload-browser');
await mkdir(screenshots, { recursive: true });
const token = `test.${Buffer.from(JSON.stringify({ sub: 'record-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const captions = {
    en: { action: 'Take a video', status: 'Uploaded' },
    fr: { action: 'Filmer une vidéo', status: 'Envoyé' },
    es: { action: 'Grabar un vídeo', status: 'Subido' },
};

async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for transfer');
        await delay(20);
    }
}

const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
});
try {
    for (const [locale, text] of Object.entries(captions)) {
        for (const [size, viewport] of Object.entries({
            mobile: { width: 390, height: 844 },
            desktop: { width: 1440, height: 1000 },
        })) {
            const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
            const rows = [];
            const gates = [];
            let rejectCreation = false;
            let expectedToken = token;
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
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/record-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                await context.route('**/record-api/**', async (route) => {
                    const request = route.request();
                    const path = new URL(request.url()).pathname.replace('/record-api', '');
                    assert.equal(request.headers().authorization, `Bearer ${expectedToken}`);
                    if (path === '/user/me') {
                        return route.fulfill({
                            json: { id: 'record-owner', terms_accepted: true },
                        });
                    }
                    if (path === '/uploads') {
                        return route.fulfill({
                            json: expectedToken === token ? rows.toReversed() : [],
                        });
                    }
                    if (path === '/buildings') {
                        return route.fulfill({
                            json: [
                                {
                                    id: 'existing',
                                    name: 'Existing building',
                                    latitude: null,
                                    longitude: null,
                                    latest_reconstruction: null,
                                },
                            ],
                        });
                    }
                    assert.ok(path.startsWith('/tus/files/'), `Unexpected request: ${path}`);
                    const headers = { 'Tus-Resumable': '1.0.0' };
                    if (request.method() === 'POST') {
                        if (rejectCreation) {
                            return route.fulfill({ status: 400, body: 'Rejected recording' });
                        }
                        const metadata = Object.fromEntries(
                            request
                                .headers()
                                ['upload-metadata'].split(',')
                                .map((part) => {
                                    const [key, value] = part.trim().split(' ');
                                    return [key, Buffer.from(value, 'base64').toString()];
                                }),
                        );
                        assert.match(metadata.filename, /^capture-.*\.(webm|mp4)$/);
                        assert.match(metadata.filetype, /^video\//);
                        const id = String(rows.length + 1).padStart(32, '0');
                        const size = Number(request.headers()['upload-length']);
                        assert.ok(size > 0);
                        rows.push({
                            id,
                            user_id: 'record-owner',
                            filename: metadata.filename,
                            name: 'TODO',
                            description: '',
                            size_bytes: size,
                            uploaded_bytes: 0,
                            status: 'pending',
                            created_at: new Date().toISOString(),
                            uploaded_at: null,
                        });
                        return route.fulfill({
                            status: 201,
                            headers: {
                                ...headers,
                                Location: `${origin}/record-api/tus/files/${id}`,
                            },
                        });
                    }
                    assert.equal(request.method(), 'PATCH');
                    const row = rows.find((row) => row.id === path.split('/').pop());
                    assert.ok(row);
                    await new Promise((resolve) => gates.push(resolve));
                    assert.equal(request.postDataBuffer().length, row.size_bytes);
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
                await page.goto(`${origin}/#/uploads`);
                const openRecorder = async () => {
                    await page.getByRole('link', { name: text.action, exact: true }).click();
                    await page.waitForURL('**/#/uploads/record');
                    await page.waitForFunction(() => {
                        const button = document.querySelector('.record-btn-rec');
                        return button && !button.disabled;
                    });
                };
                const record = async () => {
                    await page.locator('.record-btn-rec').click();
                    await page.getByRole('timer').waitFor();
                    await delay(300);
                };

                // Exercise the actual MediaRecorder and an unfinished tus transfer.
                await openRecorder();
                await record();
                await page.screenshot({ path: join(screenshots, `${locale}-${size}.png`) });
                await page.locator('.record-btn-rec').click();
                await page.waitForURL('**/#/uploads');
                await waitFor(() => gates.length === 1);
                assert.equal(rows.length, 1);
                assert.equal(rows[0].status, 'pending');
                assert.equal(await page.locator('video').count(), 0);
                assert.ok(
                    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                );
                gates.shift()();
                await page.locator('.uploads-list').getByText(rows[0].filename).waitFor();
                await page.locator('.uploads-list .q-chip').getByText(text.status).waitFor();
                await page
                    .locator('.q-notification')
                    .getByText(new RegExp(rows[0].filename))
                    .waitFor();

                // Remaining failure cases use English selectors.
                if (locale === 'en' && size === 'desktop') {
                    // Closing an active recording does not create an upload.
                    await openRecorder();
                    await record();
                    await page.locator('.record-btn-close').click();
                    await page
                        .getByRole('button', { name: 'Discard capture', exact: true })
                        .click();
                    await page.waitForURL('**/#/uploads');
                    assert.equal(rows.length, 1);

                    // Camera interruption never hands a partial recording to uploads.
                    await openRecorder();
                    await record();
                    await page.evaluate(() => {
                        document
                            .querySelector('video')
                            .srcObject.getVideoTracks()[0]
                            .dispatchEvent(new Event('ended'));
                    });
                    await page.getByRole('alert').first().waitFor();
                    assert.equal(rows.length, 1);
                    await page.locator('.record-btn-close').click();
                    await page
                        .getByRole('button', { name: 'Discard capture', exact: true })
                        .click();
                    await page.waitForURL('**/#/uploads');

                    // Denial stays in the recorder without starting a transfer.
                    await page.evaluate(() => {
                        window.restoreCameraAccess = navigator.mediaDevices.getUserMedia;
                        navigator.mediaDevices.getUserMedia = async () => {
                            throw new DOMException('Denied', 'NotAllowedError');
                        };
                    });
                    await page.getByRole('link', { name: text.action, exact: true }).click();
                    await page.getByRole('alert').first().waitFor();
                    assert.equal(await page.locator('.record-btn-rec').isDisabled(), true);
                    assert.equal(rows.length, 1);
                    await page.evaluate(() => {
                        navigator.mediaDevices.getUserMedia = window.restoreCameraAccess;
                    });
                    await page.locator('.record-btn-close').click();
                    await page
                        .getByRole('button', { name: 'Discard capture', exact: true })
                        .click();
                    await page.waitForURL('**/#/uploads');

                    // An aborted navigation can be retried without another upload.
                    await openRecorder();
                    await page.evaluate(() => {
                        const router =
                            document.querySelector('#q-app').__vue_app__.config.globalProperties
                                .$router;
                        window.removeRecordGuard = router.beforeEach((to) =>
                            to.name === 'uploads' ? false : undefined,
                        );
                    });
                    await record();
                    await page.locator('.record-btn-rec').click();
                    await page.getByRole('button', { name: 'View uploads', exact: true }).waitFor();
                    await waitFor(() => gates.length === 1);
                    assert.equal(rows.length, 2);
                    assert.equal(await page.locator('.record-btn-rec').isDisabled(), true);
                    await page.evaluate(() => window.removeRecordGuard());
                    await page.getByRole('button', { name: 'View uploads', exact: true }).click();
                    await page.waitForURL('**/#/uploads');
                    gates.shift()();
                    await page.locator('.uploads-list').getByText(rows[1].filename).waitFor();
                    assert.equal(rows.length, 2);

                    rejectCreation = true;
                    await openRecorder();
                    await record();
                    await page.locator('.record-btn-rec').click();
                    await page.waitForURL('**/#/uploads');
                    await page
                        .locator('.q-notification')
                        .getByText(/The upload of .* failed\./)
                        .waitFor();
                    assert.equal(rows.length, 2);

                    // A previous account's completed transfer cannot notify a new account.
                    rejectCreation = false;
                    await page.evaluate(() => {
                        const router =
                            document.querySelector('#q-app').__vue_app__.config.globalProperties
                                .$router;
                        return router.push({ name: 'uploads' });
                    });
                    await openRecorder();
                    await record();
                    await page.locator('.record-btn-rec').click();
                    await page.waitForURL('**/#/uploads');
                    await waitFor(() => gates.length === 1);
                    await page.locator('a[href="#/more"]:visible').click();
                    const otherToken = `test.${Buffer.from(JSON.stringify({ sub: 'other-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
                    expectedToken = otherToken;
                    await page.evaluate(
                        (value) => localStorage.setItem('access_token', value),
                        otherToken,
                    );
                    gates.shift()();
                    await waitFor(() => rows[2].status === 'uploaded');
                    await delay(500);
                    assert.equal(
                        await page
                            .locator('.q-notification')
                            .filter({ hasText: rows[2].filename })
                            .count(),
                        0,
                    );
                }
                assert.deepEqual(errors, []);
                console.log(`${locale} ${size}: camera → background upload passed`);
            } finally {
                gates.forEach((release) => release());
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
