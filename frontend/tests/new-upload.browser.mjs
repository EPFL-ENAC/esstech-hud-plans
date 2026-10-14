import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/new-upload.browser.mjs /path/to/playwright/index.mjs [dev-url] [live-api-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9020';
const liveApi = process.argv[4];
const screenshots = join(tmpdir(), 'hud-new-upload-browser');
await mkdir(screenshots, { recursive: true });
const token = `test.${Buffer.from(JSON.stringify({ sub: 'browser-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const locales = {
    en: {
        title: 'New upload',
        start: 'Upload',
        retry: 'Retry',
        empty: 'This file is empty. Choose a video with content.',
        invalid: 'This video could not be accepted. Choose a supported video file.',
        view: 'View uploads',
    },
    fr: {
        title: 'Nouvel envoi',
        start: 'Envoyer',
        retry: 'Réessayer',
        empty: 'Ce fichier est vide. Choisissez une vidéo avec du contenu.',
        invalid: 'Cette vidéo n’a pas pu être acceptée. Choisissez un fichier vidéo compatible.',
        view: 'Voir les envois',
    },
    es: {
        title: 'Subir archivo',
        start: 'Subir',
        retry: 'Reintentar',
        empty: 'Este archivo está vacío. Elige un vídeo con contenido.',
        invalid: 'No se pudo aceptar este vídeo. Elige un archivo de vídeo compatible.',
        view: 'Ver archivos',
    },
};
const video = (name) => ({ name, mimeType: 'video/mp4', buffer: Buffer.alloc(1024 * 1024, 7) });
async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for upload request');
        await delay(10);
    }
}

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [locale, text] of Object.entries(locales)) {
        for (const [size, viewport] of Object.entries({
            mobile: { width: 390, height: 844 },
            desktop: { width: 1440, height: 1000 },
        })) {
            const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
            const rows = [];
            const requests = [];
            const gates = [];
            let failCreation = false;
            let failPatch = false;
            try {
                await context.addInitScript(
                    ({ token, locale }) => {
                        localStorage.setItem('access_token', token);
                        localStorage.setItem('hud-language', locale);
                    },
                    { token, locale },
                );
                await context.route('**/env.js', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/new-uploads-smoke-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                await context.route('**/new-uploads-smoke-api/**', async (route) => {
                    const request = route.request();
                    const url = new URL(request.url());
                    const path = url.pathname.replace('/new-uploads-smoke-api', '');
                    assert.equal(request.headers().authorization, `Bearer ${token}`);
                    requests.push({ method: request.method(), path });
                    const headers = { 'Tus-Resumable': '1.0.0' };
                    if (path === '/user/me')
                        return route.fulfill({
                            json: {
                                id: 'browser-user',
                                name: 'Tester',
                                username: 'tester',
                                email: 'test@example.test',
                            },
                        });
                    if (path === '/uploads') {
                        assert.equal(request.method(), 'GET');
                        if (liveApi) {
                            const response = await route.fetch({
                                url: `${liveApi}${path}${url.search}`,
                                headers: {
                                    ...request.headers(),
                                    authorization: 'Bearer owner-token',
                                },
                            });
                            return route.fulfill({ response });
                        }
                        return route.fulfill({
                            json: rows.map(({ offset, ...row }) => row).toReversed(),
                        });
                    }
                    assert.ok(path.startsWith('/tus/files/'));
                    if (request.method() === 'POST') {
                        if (failCreation)
                            return route.fulfill({ status: 400, body: 'Invalid video' });
                        if (liveApi) {
                            const response = await route.fetch({
                                url: `${liveApi}${path}`,
                                headers: {
                                    ...request.headers(),
                                    authorization: 'Bearer owner-token',
                                },
                            });
                            const id = response.headers().location.split('/').pop();
                            return route.fulfill({
                                response,
                                headers: {
                                    ...response.headers(),
                                    location: `${origin}/new-uploads-smoke-api/tus/files/${id}`,
                                },
                            });
                        }
                        const id = `${String(rows.length + 1).padStart(32, '0')}`;
                        const filename = Buffer.from(
                            request
                                .headers()
                                ['upload-metadata'].split(',')
                                .find((part) => part.trim().startsWith('filename '))
                                .trim()
                                .split(' ')[1],
                            'base64',
                        ).toString();
                        rows.push({
                            id,
                            user_id: 'private-user',
                            name: 'TODO',
                            description: '',
                            filename,
                            size_bytes: Number(request.headers()['upload-length']),
                            file_path: '/private/file',
                            status: 'pending',
                            created_at: new Date().toISOString(),
                            uploaded_at: null,
                            offset: 0,
                        });
                        return route.fulfill({
                            status: 201,
                            headers: {
                                ...headers,
                                Location: `${origin}/new-uploads-smoke-api/tus/files/${id}`,
                            },
                        });
                    }
                    const row = rows.find((row) => row.id === path.split('/').pop());
                    if (request.method() === 'HEAD') {
                        if (liveApi) {
                            const response = await route.fetch({
                                url: `${liveApi}${path}`,
                                headers: {
                                    ...request.headers(),
                                    authorization: 'Bearer owner-token',
                                },
                            });
                            return route.fulfill({ response });
                        }
                        assert.ok(row);
                        return route.fulfill({
                            status: 200,
                            headers: {
                                ...headers,
                                'Upload-Length': String(row.size_bytes),
                                'Upload-Offset': String(row.offset),
                            },
                        });
                    }
                    assert.equal(request.method(), 'PATCH');
                    if (failPatch)
                        return route.fulfill({ status: 400, body: 'Interrupted transfer' });
                    await new Promise((resolve) => gates.push(resolve));
                    if (failPatch)
                        return route.fulfill({ status: 400, body: 'Interrupted transfer' });
                    if (liveApi) {
                        const response = await route.fetch({
                            url: `${liveApi}${path}`,
                            headers: { ...request.headers(), authorization: 'Bearer owner-token' },
                        });
                        return route.fulfill({ response });
                    }
                    assert.ok(row);
                    assert.equal(request.headers()['upload-offset'], String(row.offset));
                    row.offset += request.postDataBuffer().length;
                    row.status = 'uploaded';
                    row.uploaded_at = new Date().toISOString();
                    return route.fulfill({
                        status: 204,
                        headers: { ...headers, 'Upload-Offset': String(row.offset) },
                    });
                });
                const page = await context.newPage();
                const pageErrors = [];
                page.on('pageerror', (error) => pageErrors.push(error.message));
                await page.goto(`${origin}/#/uploads`);
                await page.getByRole('link', { name: text.title, exact: true }).click();
                const input = page.locator('input[type=file]');
                const firstFilename = `first-${locale}-${size}.mp4`;
                const start = () => page.getByRole('button', { name: text.start, exact: true });
                assert.equal(await start().isDisabled(), true);
                await input.setInputFiles({
                    name: 'empty.mp4',
                    mimeType: 'video/mp4',
                    buffer: Buffer.alloc(0),
                });
                await page.getByText(text.empty, { exact: true }).waitFor();
                assert.equal(await start().isDisabled(), true);
                await input.setInputFiles(video(firstFilename));
                assert.equal(requests.filter((r) => r.method === 'POST').length, 0);
                await start().click();
                await waitFor(() => gates.length === 1);
                assert.equal(await input.isDisabled(), true);
                await page.locator('.q-linear-progress').waitFor();
                assert.equal(requests.filter((r) => r.method === 'POST').length, 1);
                assert.ok(
                    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                );
                await page.screenshot({
                    path: join(screenshots, `${locale}-${size}-uploading.png`),
                });
                gates.shift()();
                await page.waitForURL('**/#/uploads');
                await page
                    .locator('.uploads-list')
                    .getByText(firstFilename, { exact: true })
                    .waitFor();
                assert.equal(
                    await page.locator('.uploads-list .q-chip').first().innerText(),
                    { en: 'Uploaded', fr: 'Envoyé', es: 'Subido' }[locale],
                );
                if (liveApi) {
                    console.log(
                        `${locale} ${size}: real backend/tusd upload completed and uploaded row displayed`,
                    );
                    assert.deepEqual(pageErrors, []);
                    continue;
                }

                await page.getByRole('link', { name: text.title, exact: true }).click();
                failCreation = true;
                await input.setInputFiles(video('bad.mp4'));
                await start().click();
                await page.getByText(text.invalid, { exact: true }).waitFor();
                await page.screenshot({ path: join(screenshots, `${locale}-${size}-error.png`) });
                failCreation = false;
                await input.setInputFiles(video('retry.mp4'));
                assert.equal(await page.getByText(text.invalid, { exact: true }).count(), 0);
                failPatch = true;
                await start().click();
                await page.getByRole('button', { name: text.retry, exact: true }).waitFor();
                failPatch = false;
                await page.evaluate(() => {
                    const router =
                        document.querySelector('#q-app').__vue_app__.config.globalProperties
                            .$router;
                    window.removeUploadNavigationGuard = router.beforeEach((to) =>
                        to.name === 'uploads' ? false : undefined,
                    );
                });
                await page.getByRole('button', { name: text.retry, exact: true }).click();
                await waitFor(() => gates.length === 1);
                assert.ok(requests.some((r) => r.method === 'HEAD'));
                const retryRows = rows.filter((row) => row.filename === 'retry.mp4');
                assert.equal(retryRows.length, 1);
                gates.shift()();
                await page.getByRole('button', { name: text.view, exact: true }).waitFor();
                assert.ok(page.url().endsWith('/#/uploads/new'));
                assert.equal(await input.isDisabled(), true);
                await page.evaluate(() => window.removeUploadNavigationGuard());
                await page.getByRole('button', { name: text.view, exact: true }).click();
                await page.waitForURL('**/#/uploads');

                await page.getByRole('link', { name: text.title, exact: true }).click();
                await input.setInputFiles(video('background-a.mp4'));
                await start().click();
                await waitFor(() => gates.length === 1);
                await page.locator('a[href="#/more"]:visible').click();
                await page.locator('a[href="#/uploads"]').click();
                await page.getByRole('link', { name: text.title, exact: true }).click();
                await input.setInputFiles(video('background-b.mp4'));
                await start().click();
                await waitFor(() => gates.length === 2);
                gates.shift()();
                await page
                    .locator('.q-notification')
                    .getByText(/background-a\.mp4/)
                    .waitFor();
                assert.ok(page.url().endsWith('/#/uploads/new'));
                await page.getByText('background-b.mp4', { exact: true }).waitFor();
                assert.equal(await input.isDisabled(), true);
                gates.shift()();
                await page.waitForURL('**/#/uploads');
                await page
                    .locator('.uploads-list')
                    .getByText('background-a.mp4', { exact: true })
                    .waitFor();
                await page
                    .locator('.uploads-list')
                    .getByText('background-b.mp4', { exact: true })
                    .waitFor();

                await page.getByRole('link', { name: text.title, exact: true }).click();
                await input.setInputFiles(video('background-failed.mp4'));
                await start().click();
                await waitFor(() => gates.length === 1);
                await page.locator('a[href="#/more"]:visible').click();
                failPatch = true;
                gates.shift()();
                await page
                    .locator('.q-notification')
                    .getByText(/background-failed\.mp4/)
                    .waitFor();
                assert.ok(page.url().endsWith('/#/more'));
                assert.equal(requests.filter((r) => r.method === 'DELETE').length, 0);
                assert.deepEqual(pageErrors, []);
                console.log(
                    `${locale} ${size}: picker, progress, completion, retry/resume, concurrent background success/failure passed`,
                );
            } finally {
                gates.forEach((release) => release());
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
