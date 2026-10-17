import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// node tests/upload-picker.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9040';
const screenshots = join(tmpdir(), 'hud-upload-picker-browser');
await mkdir(screenshots, { recursive: true });
const token = `test.${Buffer.from(JSON.stringify({ sub: 'picker-user', exp: 4_000_000_000 })).toString('base64url')}.test`;
const rows = Array.from({ length: 25 }, (_, index) => ({
    id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
    user_id: 'picker-user',
    filename: index === 0 ? `${'long-video-name-'.repeat(8)}.mp4` : `video-${index + 1}.mp4`,
    name: index === 1 ? 'North facade' : 'TODO',
    description: '',
    size_bytes: 12_000_000,
    status: 'uploaded',
    created_at: '2026-10-15T10:00:00Z',
    uploaded_at: '2026-10-15T10:05:00Z',
}));
const captions = {
    en: {
        action: 'Uploaded video',
        title: 'Choose an uploaded video',
        use: 'Use video',
        cancel: 'Cancel',
        retry: 'Retry',
        empty: 'No completed video uploads yet.',
        failed: 'Could not load your uploads.',
    },
    fr: {
        action: 'Vidéo déjà envoyée',
        title: 'Choisir une vidéo envoyée',
        use: 'Utiliser la vidéo',
        cancel: 'Annuler',
        retry: 'Réessayer',
        empty: 'Aucun envoi de vidéo terminé pour le moment.',
        failed: 'Impossible de charger vos envois.',
    },
    es: {
        action: 'Vídeo ya subido',
        title: 'Elegir un vídeo subido',
        use: 'Usar vídeo',
        cancel: 'Cancelar',
        retry: 'Reintentar',
        empty: 'Aún no hay vídeos subidos por completo.',
        failed: 'No se pudieron cargar tus archivos.',
    },
};
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [locale, text] of Object.entries(captions)) {
        for (const [size, viewport] of Object.entries({
            mobile: { width: 390, height: 844 },
            desktop: { width: 1440, height: 1000 },
        })) {
            const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
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
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/picker-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                let mode = 'error';
                const uploadRequests = [];
                const submissions = [];
                await context.route('**/picker-api/**', async (route) => {
                    const request = route.request();
                    const url = new URL(request.url());
                    assert.equal(request.headers().authorization, `Bearer ${token}`);
                    if (url.pathname.endsWith('/user/me')) {
                        return route.fulfill({ json: { id: 'picker-user', terms_accepted: true } });
                    }
                    if (url.pathname.endsWith('/uploads')) {
                        assert.equal(request.method(), 'GET');
                        assert.equal(url.searchParams.get('status'), 'uploaded');
                        assert.equal(url.searchParams.get('limit'), '21');
                        const offset = Number(url.searchParams.get('offset'));
                        uploadRequests.push(offset);
                        if (mode === 'error')
                            return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
                        return route.fulfill({
                            json: mode === 'empty' ? [] : rows.slice(offset, offset + 21),
                        });
                    }
                    if (request.method() === 'POST') {
                        submissions.push({ path: url.pathname, body: request.postDataJSON() });
                        return route.fulfill({
                            status: 409,
                            json: { detail: 'Upload unavailable' },
                        });
                    }
                    if (url.pathname.endsWith('/buildings')) {
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
                    return route.fulfill({ json: [] });
                });
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                await page.goto(`${origin}/#/capture?buildingId=existing`);
                const action = page.getByRole('button', { name: text.action, exact: true });
                await action.waitFor();
                assert.equal(uploadRequests.length, 0);
                await action.click();
                const dialog = page.getByRole('dialog');
                await dialog.getByText(text.title, { exact: true }).waitFor();
                await dialog.getByText(text.failed, { exact: true }).waitFor();
                mode = 'data';
                await dialog.getByRole('button', { name: text.retry, exact: true }).click();
                await dialog.getByText(rows[0].filename, { exact: true }).waitFor();
                assert.equal(await dialog.locator('.picker-upload').count(), 20);
                assert.ok(!(await dialog.innerText()).includes('TODO'));
                await page.screenshot({ path: join(screenshots, `${locale}-${size}-picker.png`) });
                assert.equal(
                    await dialog.getByRole('button', { name: text.use, exact: true }).isDisabled(),
                    true,
                );
                await dialog.getByRole('button', { name: '2', exact: true }).click();
                await dialog.getByText('video-21.mp4', { exact: true }).waitFor();
                assert.equal(uploadRequests.at(-1), 20);
                assert.equal(await dialog.locator('.picker-upload').count(), 5);
                await dialog.getByText('video-21.mp4', { exact: true }).click();
                await dialog.getByRole('button', { name: text.cancel, exact: true }).click();
                await dialog.waitFor({ state: 'hidden' });
                assert.equal(await page.locator('.selected-upload').count(), 0);

                await action.click();
                await dialog.getByText(rows[0].filename, { exact: true }).waitFor();
                await dialog.getByText(rows[0].filename, { exact: true }).click();
                await dialog.getByRole('button', { name: text.use, exact: true }).click();
                await dialog.waitFor({ state: 'hidden' });
                await page
                    .locator('.selected-upload')
                    .getByText(rows[0].filename, { exact: true })
                    .waitFor();
                assert.equal(
                    await page.evaluate(
                        () => document.documentElement.scrollWidth <= window.innerWidth,
                    ),
                    true,
                );
                await page.screenshot({
                    path: join(screenshots, `${locale}-${size}-selected.png`),
                });

                if (locale === 'en') {
                    // A canceled picker keeps the current upload.
                    await action.click();
                    await dialog.getByText('video-2.mp4', { exact: true }).click();
                    await dialog.getByRole('button', { name: text.cancel, exact: true }).click();
                    await dialog.waitFor({ state: 'hidden' });
                    await page
                        .locator('.selected-upload')
                        .getByText(rows[0].filename, { exact: true })
                        .waitFor();

                    // Selecting a local file replaces the upload.
                    await page.locator('input[type=file]').setInputFiles({
                        name: 'local.mp4',
                        mimeType: 'video/mp4',
                        buffer: Buffer.from('video'),
                    });
                    assert.equal(await page.locator('.selected-upload').count(), 0);
                    await action.click();
                    await dialog.getByText('video-2.mp4', { exact: true }).click();
                    await dialog.getByRole('button', { name: text.use, exact: true }).click();
                    await dialog.waitFor({ state: 'hidden' });
                    assert.equal(await page.locator('video.video-preview').count(), 0);

                    // The recorder draft preserves the upload when recording is discarded.
                    await page.getByRole('button', { name: 'Take a Video', exact: true }).click();
                    await page.waitForURL('**/#/capture/record');
                    await page.evaluate(() => {
                        window.location.hash = '#/capture?buildingId=existing';
                    });
                    await action.waitFor();
                    await page
                        .locator('.selected-upload')
                        .getByText('video-2.mp4', { exact: true })
                        .waitFor();
                    const start = page.getByRole('button', {
                        name: 'Start Processing (10-60min)',
                        exact: true,
                    });
                    await start.click();
                    await page.getByText('Upload unavailable', { exact: true }).waitFor();
                    assert.equal(
                        submissions.at(-1).path,
                        '/picker-api/buildings/existing/reconstructions/from-upload',
                    );
                    assert.equal(submissions.at(-1).body.upload_id, rows[1].id);

                    await page.goto(`${origin}/#/buildings/new`);
                    await action.click();
                    await dialog.getByText('video-3.mp4', { exact: true }).click();
                    await dialog.getByRole('button', { name: text.use, exact: true }).click();
                    await dialog.waitFor({ state: 'hidden' });
                    await page
                        .getByRole('button', { name: 'Create and submit', exact: true })
                        .click();
                    await page.getByText('Upload unavailable', { exact: true }).waitFor();
                    assert.equal(
                        submissions.at(-1).path,
                        '/picker-api/buildings/from-reconstruction/from-upload',
                    );
                    assert.equal(submissions.at(-1).body.upload_id, rows[2].id);

                    await page.reload();
                    mode = 'empty';
                    await action.click();
                    await dialog.getByText(text.empty, { exact: true }).waitFor();
                    assert.equal(
                        await dialog
                            .getByRole('button', { name: text.use, exact: true })
                            .isDisabled(),
                        true,
                    );
                }
                assert.deepEqual(errors, []);
                console.log(
                    `${locale} ${size}: picker, pagination, cancellation, selection passed`,
                );
            } finally {
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
