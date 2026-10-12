import assert from 'node:assert/strict';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Like pwa.browser.mjs, use an existing Playwright installation.
// Run against the dev server with a short, valid video fixture:
// node tests/upload.browser.mjs /path/to/playwright/index.mjs /path/to/scan.mp4 [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const videoPath = process.argv[3];
assert.ok(videoPath, 'Provide a short, valid video fixture');
const origin = process.argv[4] ?? 'http://localhost:9010';
const locales = {
    en: {
        upload: 'Uploading video',
        resume: 'Resuming upload...',
        submitting: 'Submitting reconstruction…',
        start: 'Start Processing (10-60min)',
    },
    fr: {
        upload: 'Envoi de la vidéo',
        resume: 'Reprise de l’envoi de la vidéo...',
        submitting: 'Envoi de la reconstruction…',
        start: 'Démarrer le traitement (10–60 min)',
    },
    es: {
        upload: 'Subiendo el vídeo',
        resume: 'Reanudando la subida del vídeo...',
        submitting: 'Enviando la reconstrucción…',
        start: 'Iniciar el procesamiento (10–60 min)',
    },
};
const token = `test.${Buffer.from(
    JSON.stringify({
        sub: 'upload-browser-test',
        exp: 4_000_000_000,
    }),
).toString('base64url')}.test`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [locale, captions] of Object.entries(locales)) {
        for (const path of ['/capture', '/buildings/new']) {
            const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
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
                        body: `window.env = ${JSON.stringify({
                            API_URL: origin,
                            API_PATH: '/upload-smoke-api',
                            KEYCLOAK_ENDPOINT: origin,
                            KEYCLOAK_REALM: 'test',
                            KEYCLOAK_CLIENT_ID: 'test',
                            SENTRY_RATE: '0',
                        })};`,
                    }),
                );
                // Mock only the transport boundary; render real pages, mutation, and progress UI.
                await context.route('**/src/lib/utils/tusUpload.ts*', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: `export function uploadVideoResumable(file, options) {
                        return new Promise((resolve, reject) => {
                            window.__uploadTest = { options, resolve, reject };
                            options.onProgress({ loaded: 1048576, total: 0 });
                        });
                    }`,
                    }),
                );
                let submissions = 0;
                let submissionBody;
                let releaseSubmission;
                let notifySubmission;
                const submitted = new Promise((resolve) => (releaseSubmission = resolve));
                const submissionStarted = new Promise((resolve) => (notifySubmission = resolve));
                await context.route('**/upload-smoke-api/**', async (route) => {
                    if (route.request().method() === 'POST') {
                        submissions++;
                        submissionBody = route.request().postDataJSON();
                        notifySubmission();
                        await submitted;
                        await route.fulfill({
                            status: 503,
                            contentType: 'application/json',
                            body: JSON.stringify({ detail: 'Browser test scheduling failure' }),
                        });
                    } else {
                        await route.fulfill({ contentType: 'application/json', body: '[]' });
                    }
                });
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                await page.goto(`${origin}/#${path}`);
                await page.locator('input[type=file]').setInputFiles(videoPath);
                const start = page.getByRole('button', {
                    name: path === '/capture' ? captions.start : 'Create and submit',
                    exact: true,
                });
                await start.click();
                const progress = page
                    .getByRole('status')
                    .filter({ has: page.getByRole('progressbar') });
                await progress.filter({ hasText: captions.upload }).waitFor();
                assert.match(await progress.innerText(), /1\.0/);
                assert.equal(
                    await progress.getByRole('progressbar').getAttribute('aria-valuenow'),
                    null,
                );
                await page.evaluate(() =>
                    window.__uploadTest.options.onProgress({
                        loaded: 1048576,
                        total: 2097152,
                    }),
                );
                await progress.getByText(/2\.0/).waitFor();
                assert.equal(
                    await progress.getByRole('progressbar').getAttribute('aria-valuenow'),
                    '0.5',
                );
                await page.evaluate(() => window.__uploadTest.options.onResumed());
                await page.getByRole('status').filter({ hasText: captions.resume }).waitFor();
                await page.evaluate(() =>
                    window.__uploadTest.reject(new Error('Browser test upload failure')),
                );
                await progress.waitFor({ state: 'detached' });
                assert.equal(submissions, 0);

                await start.click();
                await page.getByRole('status').filter({ hasText: captions.upload }).waitFor();
                await page.evaluate(() =>
                    window.__uploadTest.resolve({ uploadId: 'browser-upload' }),
                );
                const submitting = page
                    .getByRole('status')
                    .filter({ hasText: captions.submitting });
                await submitting.waitFor();
                await submissionStarted;
                assert.equal(
                    await submitting.getByRole('progressbar').getAttribute('aria-valuenow'),
                    null,
                );
                assert.equal(submissions, 1);
                assert.equal(submissionBody.tus_upload_id, 'browser-upload');
                assert.ok(submissionBody.building);
                await submitting.screenshot({
                    path: join(
                        tmpdir(),
                        `hud-upload-${locale}-${path === '/capture' ? 'capture' : 'new'}.png`,
                    ),
                });
                releaseSubmission();
                await page.getByText('Browser test scheduling failure', { exact: true }).waitFor();
                await progress.waitFor({ state: 'detached' });
                assert.deepEqual(errors, []);
                console.log(
                    `PASS: ${locale} ${path}: unknown/known size, resume, upload failure, delayed submission, submission failure`,
                );
            } finally {
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
