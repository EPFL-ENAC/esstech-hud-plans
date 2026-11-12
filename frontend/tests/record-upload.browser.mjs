import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
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
const captureLimited =
    'This browser cannot limit the recording. The file may be larger than usual.';
const captureMaxSide = 1280;

async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for transfer');
        await delay(20);
    }
}

// Decodes an uploaded file in the page and measures its size and average frame
// rate by playing it and counting requestVideoFrameCallback callbacks.
async function inspectVideo(page, bytes, countFrames = true) {
    return page.evaluate(
        async ({ base64, countFrames }) => {
            const binary = atob(base64);
            const url = URL.createObjectURL(
                new Blob([Uint8Array.from(binary, (character) => character.charCodeAt(0))]),
            );
            const video = document.createElement('video');
            video.muted = true;
            video.src = url;
            try {
                await new Promise((resolve, reject) => {
                    video.onloadedmetadata = () => resolve();
                    video.onerror = () =>
                        reject(new Error('The uploaded file is not a playable video'));
                });
                if (!Number.isFinite(video.duration)) {
                    // MediaRecorder writes no duration; seeking makes Chrome compute it.
                    video.currentTime = 1e101;
                    await new Promise((resolve) => {
                        video.ondurationchange = () => resolve();
                        setTimeout(resolve, 2000);
                    });
                    video.currentTime = 0;
                }
                const width = video.videoWidth;
                const height = video.videoHeight;
                const duration = video.duration;
                if (!countFrames) return { width, height, duration, frames: null, fps: null };
                if (typeof video.requestVideoFrameCallback !== 'function') {
                    throw new Error('requestVideoFrameCallback is not supported by this browser');
                }
                let frames = 0;
                let timer = null;
                await new Promise((resolve) => {
                    const count = () => {
                        frames++;
                        if (video.ended) return resolve();
                        video.requestVideoFrameCallback(count);
                    };
                    video.addEventListener('ended', resolve);
                    video.requestVideoFrameCallback(count);
                    void video.play();
                    timer = setTimeout(resolve, 10_000);
                });
                clearTimeout(timer);
                return {
                    width,
                    height,
                    duration,
                    frames,
                    fps: Number.isFinite(duration) && duration > 0 ? frames / duration : null,
                };
            } finally {
                URL.revokeObjectURL(url);
            }
        },
        { base64: bytes.toString('base64'), countFrames },
    );
}

const createRecordApi = (state) => async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/record-api', '');
    assert.equal(request.headers().authorization, `Bearer ${state.expectedToken}`);
    if (path === '/user/me') {
        return route.fulfill({
            json: { id: 'record-owner', terms_accepted: true },
        });
    }
    if (path === '/uploads') {
        return route.fulfill({
            json: {
                items: state.expectedToken === token ? state.rows.toReversed() : [],
                total: state.expectedToken === token ? state.rows.length : 0,
            },
        });
    }
    if (path.startsWith('/buildings/')) {
        return path === '/buildings/existing'
            ? route.fulfill({
                  json: {
                      id: 'existing',
                      name: 'Existing building',
                      latitude: null,
                      longitude: null,
                  },
              })
            : route.fulfill({
                  status: 404,
                  json: { detail: 'Building not found' },
              });
    }
    if (path === '/buildings') {
        return route.fulfill({
            json: {
                items: [
                    {
                        id: 'existing',
                        name: 'Existing building',
                        latitude: null,
                        longitude: null,
                        latest_reconstruction: null,
                    },
                ],
                total: 1,
            },
        });
    }
    assert.ok(path.startsWith('/tus/files/'), `Unexpected request: ${path}`);
    const headers = { 'Tus-Resumable': '1.0.0' };
    if (request.method() === 'POST') {
        if (state.rejectCreation) {
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
        const id = String(state.rows.length + 1).padStart(32, '0');
        const size = Number(request.headers()['upload-length']);
        assert.ok(size > 0);
        state.rows.push({
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
    const row = state.rows.find((row) => row.id === path.split('/').pop());
    assert.ok(row);
    await new Promise((resolve) => state.gates.push(resolve));
    const body = request.postDataBuffer();
    assert.equal(body.length, row.size_bytes);
    state.uploaded = body;
    row.status = 'uploaded';
    row.uploaded_bytes = row.size_bytes;
    row.uploaded_at = new Date().toISOString();
    return route.fulfill({
        status: 204,
        headers: { ...headers, 'Upload-Offset': String(row.size_bytes) },
    });
};

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
            const api = {
                rows,
                gates,
                expectedToken: token,
                rejectCreation: false,
                uploaded: null,
            };
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
                await context.route('**/record-api/**', createRecordApi(api));

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

                    api.rejectCreation = true;
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
                    api.rejectCreation = false;
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
                    api.expectedToken = otherToken;
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

                    // A long recording is capped in size and frame rate by the canvas.
                    await page.evaluate(() => {
                        const router =
                            document.querySelector('#q-app').__vue_app__.config.globalProperties
                                .$router;
                        return router.push({ name: 'uploads' });
                    });
                    await openRecorder();
                    await record();
                    await delay(2500);
                    assert.equal(
                        await page.locator('.record-capture-notice').count(),
                        0,
                        'The canvas path must not warn about limited capture',
                    );
                    await page.locator('.record-btn-rec').click();
                    await page.waitForURL('**/#/uploads');
                    await waitFor(() => gates.length === 1);
                    assert.equal(rows.length, 4);
                    gates.shift()();
                    await waitFor(() => rows[3].status === 'uploaded');
                    const captured = await inspectVideo(page, api.uploaded);
                    console.log(
                        `canvas capture: ${captured.width}x${captured.height}, ${captured.fps} fps over ${captured.duration}s (${captured.frames} frames)`,
                    );
                    assert.ok(captured.width > 0 && captured.height > 0);
                    assert.ok(
                        Math.max(captured.width, captured.height) === captureMaxSide,
                        `Recorded ${captured.width}x${captured.height}`,
                    );
                    assert.ok(
                        captured.fps !== null,
                        'Could not measure the frame rate of the recording',
                    );
                    assert.ok(
                        captured.fps >= 3 && captured.fps <= 6,
                        `Measured ${captured.fps} fps`,
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

    // A browser without canvas capture records the raw camera stream and warns.
    {
        const context = await browser.newContext({
            viewport: { width: 1440, height: 1000 },
            serviceWorkers: 'block',
        });
        const api = {
            rows: [],
            gates: [],
            expectedToken: token,
            rejectCreation: false,
            uploaded: null,
        };
        try {
            await context.addInitScript(() => {
                delete HTMLCanvasElement.prototype.captureStream;
            });
            await context.addInitScript(
                ({ token, locale }) => {
                    localStorage.setItem('access_token', token);
                    localStorage.setItem('hud-language', locale);
                    localStorage.setItem('hud-hide-video-tips', 'true');
                },
                { token, locale: 'en' },
            );
            await context.route('**/env.js', (route) =>
                route.fulfill({
                    contentType: 'application/javascript',
                    body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/record-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                }),
            );
            await context.route('**/record-api/**', createRecordApi(api));

            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', (error) => errors.push(error.message));
            await page.goto(`${origin}/#/uploads`);
            await page.getByRole('link', { name: captions.en.action, exact: true }).click();
            await page.waitForURL('**/#/uploads/record');
            await page.waitForFunction(() => {
                const button = document.querySelector('.record-btn-rec');
                return button && !button.disabled;
            });
            await page.locator('.record-btn-rec').click();
            await page.getByRole('alert').getByText(captureLimited, { exact: true }).waitFor();
            await delay(300);
            await page.locator('.record-btn-rec').click();
            await page.waitForURL('**/#/uploads');
            await waitFor(() => api.gates.length === 1);
            assert.equal(api.rows.length, 1);
            api.gates.shift()();
            await waitFor(() => api.rows[0].status === 'uploaded');
            await page.locator('.uploads-list').getByText(api.rows[0].filename).waitFor();
            await page.locator('.uploads-list .q-chip').getByText(captions.en.status).waitFor();
            const fallback = await inspectVideo(page, api.uploaded, false);
            console.log(`fallback capture: ${fallback.width}x${fallback.height}`);
            assert.ok(fallback.width > 0 && fallback.height > 0);
            assert.deepEqual(errors, []);
            console.log('en desktop: limited capture fallback passed');
        } finally {
            api.gates.forEach((release) => release());
            await context.close();
        }
    }

    // A camera source larger than the cap is downscaled with its aspect preserved.
    {
        const sourceWidth = 1920;
        const sourceHeight = 1080;
        const sourceFrame = Buffer.alloc(
            sourceWidth * sourceHeight + 2 * ((sourceWidth / 2) * (sourceHeight / 2)),
            128,
        );
        sourceFrame.fill(16, 0, sourceWidth * sourceHeight);
        const sourceChunks = [Buffer.from('YUV4MPEG2 W1920 H1080 F30:1 Ip A1:1 C420jpeg\n')];
        for (let index = 0; index < 3; index++) {
            sourceChunks.push(Buffer.from('FRAME\n'), sourceFrame);
        }
        const sourcePath = join(screenshots, 'source-1920x1080.y4m');
        await writeFile(sourcePath, Buffer.concat(sourceChunks));

        const sourceBrowser = await chromium.launch({
            channel: 'chrome',
            headless: true,
            args: [
                '--use-fake-device-for-media-stream',
                '--use-fake-ui-for-media-stream',
                `--use-file-for-fake-video-capture=${sourcePath}`,
            ],
        });
        try {
            const context = await sourceBrowser.newContext({
                viewport: { width: 1440, height: 1000 },
                serviceWorkers: 'block',
            });
            const api = {
                rows: [],
                gates: [],
                expectedToken: token,
                rejectCreation: false,
                uploaded: null,
            };
            try {
                await context.addInitScript(() => {
                    // The camera ask keeps the feed at 1280x720, so the canvas cap
                    // needs a larger source to be exercised.
                    const mediaDevices = navigator.mediaDevices;
                    if (!mediaDevices) return;
                    const getUserMedia = mediaDevices.getUserMedia.bind(mediaDevices);
                    mediaDevices.getUserMedia = (constraints) => {
                        if (!constraints?.video || typeof constraints.video !== 'object') {
                            return getUserMedia(constraints);
                        }
                        const { width, height, ...video } = constraints.video;
                        return getUserMedia({ ...constraints, video });
                    };
                });
                await context.addInitScript(
                    ({ token, locale }) => {
                        localStorage.setItem('access_token', token);
                        localStorage.setItem('hud-language', locale);
                        localStorage.setItem('hud-hide-video-tips', 'true');
                    },
                    { token, locale: 'en' },
                );
                await context.route('**/env.js', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/record-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                await context.route('**/record-api/**', createRecordApi(api));

                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                await page.goto(`${origin}/#/uploads`);
                await page.getByRole('link', { name: captions.en.action, exact: true }).click();
                await page.waitForURL('**/#/uploads/record');
                await page.waitForFunction(() => {
                    const button = document.querySelector('.record-btn-rec');
                    return button && !button.disabled;
                });
                await page.locator('.record-btn-rec').click();
                await page.getByRole('timer').waitFor();
                await delay(1000);
                const source = await page.evaluate(() => {
                    const video = document.querySelector('video');
                    return { width: video.videoWidth, height: video.videoHeight };
                });
                assert.ok(
                    Math.max(source.width, source.height) > captureMaxSide,
                    `The fake camera delivered ${source.width}x${source.height}; the 1920x1080 fixture was not used above ${captureMaxSide}px, so downscaling cannot be verified`,
                );
                await page.locator('.record-btn-rec').click();
                await page.waitForURL('**/#/uploads');
                await waitFor(() => api.gates.length === 1);
                assert.equal(api.rows.length, 1);
                api.gates.shift()();
                await waitFor(() => api.rows[0].status === 'uploaded');
                await page.locator('.uploads-list').getByText(api.rows[0].filename).waitFor();
                const downscaled = await inspectVideo(page, api.uploaded);
                console.log(
                    `downscaled capture: ${source.width}x${source.height} → ${downscaled.width}x${downscaled.height}, ${downscaled.fps} fps over ${downscaled.duration}s (${downscaled.frames} frames)`,
                );
                assert.equal(
                    Math.max(downscaled.width, downscaled.height),
                    captureMaxSide,
                    `Recorded ${downscaled.width}x${downscaled.height}`,
                );
                assert.ok(
                    downscaled.fps !== null,
                    'Could not measure the frame rate of the recording',
                );
                assert.ok(
                    downscaled.fps >= 3 && downscaled.fps <= 6,
                    `Measured ${downscaled.fps} fps`,
                );
                const ratio = downscaled.width / downscaled.height;
                assert.ok(
                    Math.abs(ratio - sourceWidth / sourceHeight) <=
                        (sourceWidth / sourceHeight) * 0.02,
                    `Recorded aspect ratio ${ratio} instead of ${sourceWidth / sourceHeight}`,
                );
                assert.equal(Math.min(downscaled.width, downscaled.height) % 2, 0);
                assert.deepEqual(errors, []);
                console.log('en desktop: downscaled capture passed');
            } finally {
                api.gates.forEach((release) => release());
                await context.close();
            }
        } finally {
            await sourceBrowser.close();
        }
    }
} finally {
    await browser.close();
}
