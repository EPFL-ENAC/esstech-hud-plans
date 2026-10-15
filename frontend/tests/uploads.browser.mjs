import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// Render the real page and Colada query, mocking only the authenticated HTTP boundary.
// node tests/uploads.browser.mjs /path/to/playwright/index.mjs [dev-url] [screenshots-dir]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const screenshots = process.argv[4] ?? join(tmpdir(), 'hud-uploads-browser');
await mkdir(screenshots, { recursive: true });
const captions = {
    en: {
        title: 'Uploads',
        back: 'Back',
        refresh: 'Refresh',
        retry: 'Retry',
        loading: 'Loading uploads…',
        empty: 'No uploads yet.',
        emptyPage: 'No uploads on this page. Try a previous page.',
        loadFailed: 'Could not load your uploads.',
        refreshFailed: 'Could not refresh your uploads. Previously loaded uploads are shown below.',
        pagination: 'Upload list pagination',
        statuses: ['Pending', 'Uploaded', 'Failed'],
    },
    fr: {
        title: 'Envois',
        back: 'Retour',
        refresh: 'Actualiser',
        retry: 'Réessayer',
        loading: 'Chargement des envois…',
        empty: 'Aucun envoi pour le moment.',
        emptyPage: 'Aucun envoi sur cette page. Essayez une page précédente.',
        loadFailed: 'Impossible de charger vos envois.',
        refreshFailed:
            'Impossible d’actualiser vos envois. Les envois déjà chargés restent affichés ci-dessous.',
        pagination: 'Pagination de la liste des envois',
        statuses: ['En attente', 'Envoyé', 'Échec'],
    },
    es: {
        title: 'Archivos',
        back: 'Volver',
        refresh: 'Actualizar',
        retry: 'Reintentar',
        loading: 'Cargando archivos…',
        empty: 'Aún no hay archivos subidos.',
        emptyPage: 'No hay archivos en esta página. Prueba una página anterior.',
        loadFailed: 'No se pudieron cargar tus archivos.',
        refreshFailed:
            'No se pudieron actualizar tus archivos. Los archivos ya cargados se muestran abajo.',
        pagination: 'Paginación de la lista de archivos',
        statuses: ['Pendiente', 'Subido', 'Fallido'],
    },
};
const token = `test.${Buffer.from(JSON.stringify({ sub: 'uploads-browser-user', exp: 4_000_000_000 })).toString('base64url')}.test`;
const rows = Array.from({ length: 25 }, (_, index) => ({
    id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
    user_id: 'browser-user-private-id',
    name: index === 1 ? 'North facade' : 'TODO',
    description: index === 1 ? 'Recorded from the courtyard.' : '',
    filename:
        index === 0 ? `${'very_long_video_filename_'.repeat(5)}.mp4` : `video-${index + 1}.mp4`,
    size_bytes: index === 2 ? 0 : 12_400_000,
    status: ['pending', 'uploaded', 'failed'][index % 3],
    created_at: '2026-10-14T10:00:00Z',
    uploaded_at: index % 3 === 1 ? '2026-10-14T10:05:00Z' : null,
}));

async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for a mocked API request');
        await delay(10);
    }
}

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [locale, text] of Object.entries(captions)) {
        for (const [viewportName, viewport] of Object.entries({
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
                        body: `window.env = ${JSON.stringify({
                            API_URL: origin,
                            API_PATH: '/uploads-smoke-api',
                            KEYCLOAK_ENDPOINT: origin,
                            KEYCLOAK_REALM: 'test',
                            KEYCLOAK_CLIENT_ID: 'test',
                            SENTRY_RATE: '0',
                        })};`,
                    }),
                );
                let mode = 'data';
                let hold = true;
                let release;
                const requests = [];
                await context.route('**/uploads-smoke-api/**', async (route) => {
                    const request = route.request();
                    const url = new URL(request.url());
                    assert.equal(request.method(), 'GET');
                    assert.equal(request.headers().authorization, `Bearer ${token}`);
                    if (url.pathname.endsWith('/user/me')) {
                        return route.fulfill({
                            json: {
                                id: 'browser-user-private-id',
                                username: 'tester',
                                name: 'Test account',
                                email: 'tester@example.test',
                                created_at: '2026-10-14T10:00:00Z',
                                updated_at: '2026-10-14T10:00:00Z',
                            },
                        });
                    }
                    assert.equal(url.pathname, '/uploads-smoke-api/uploads');
                    assert.equal(url.searchParams.get('limit'), '21');
                    assert.equal(url.searchParams.get('sort_order'), 'desc');
                    const offset = Number(url.searchParams.get('offset'));
                    requests.push(offset);
                    if (hold)
                        await new Promise((resolve) => {
                            release = resolve;
                        });
                    if (mode === 'error')
                        return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
                    const body =
                        mode === 'empty' || (mode === 'empty-page' && offset > 0)
                            ? []
                            : rows.slice(offset, offset + 21);
                    return route.fulfill({ json: body });
                });
                const page = await context.newPage();
                const items = page.locator('.uploads-list').getByRole('listitem');
                async function capture(state) {
                    if (locale === 'en')
                        await page.screenshot({
                            path: join(screenshots, `${locale}-${viewportName}-${state}.png`),
                        });
                }
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                await page.goto(`${origin}/#/more`);
                await page.locator('a[href="#/uploads"]').click();
                await waitFor(() => release !== undefined);
                await page.getByRole('status', { name: text.loading, exact: true }).waitFor();
                await capture('loading');
                assert.equal(
                    await page
                        .getByRole('button', { name: text.refresh, exact: true })
                        .isDisabled(),
                    true,
                );
                hold = false;
                release();
                release = undefined;
                await items.first().waitFor();
                assert.equal(await items.count(), 20);
                for (const status of text.statuses)
                    await page
                        .locator('.q-chip')
                        .getByText(status, { exact: true })
                        .first()
                        .waitFor();
                await page.getByText('North facade', { exact: true }).waitFor();
                const bodyText = await page.locator('body').innerText();
                assert.ok(!bodyText.includes('TODO'));
                assert.ok(!bodyText.includes('browser-user-private-id'));
                assert.equal(await page.locator('input[type=file]').count(), 0);
                assert.equal(
                    await page.evaluate(
                        () => document.documentElement.scrollWidth <= window.innerWidth,
                    ),
                    true,
                );
                await page.screenshot({
                    path: join(screenshots, `${locale}-${viewportName}-uploads.png`),
                });

                const pagination = page.getByRole('navigation', { name: text.pagination });
                hold = true;
                await pagination.getByRole('button', { name: '2', exact: true }).click();
                await waitFor(() => release !== undefined);
                assert.equal(requests.at(-1), 20);
                assert.equal(
                    await pagination.getByRole('button', { name: '2', exact: true }).isDisabled(),
                    true,
                );
                hold = false;
                release();
                release = undefined;
                await page.getByText('video-21.mp4', { exact: true }).waitFor();
                assert.equal(await items.count(), 5);
                await capture('page-two');
                assert.equal(
                    await pagination.getByRole('button', { name: '3', exact: true }).count(),
                    0,
                );
                await page.getByRole('button', { name: text.back, exact: true }).click();
                await page.locator('a[href="#/uploads"]').click();
                await page.getByText(rows[0].filename, { exact: true }).waitFor();
                assert.equal(await items.count(), 20);
                assert.deepEqual(requests, [0, 20]);

                mode = 'error';
                await page.getByRole('button', { name: text.refresh, exact: true }).click();
                await page.getByText(text.refreshFailed, { exact: true }).waitFor();
                assert.equal(await items.count(), 20);
                mode = 'empty';
                await capture('refresh-error');
                await page.getByRole('button', { name: text.retry, exact: true }).click();
                await page.getByText(text.empty, { exact: true }).waitFor();
                await capture('empty');
                assert.equal(
                    await page.getByRole('navigation', { name: text.pagination }).count(),
                    0,
                );

                mode = 'error';
                await page.reload();
                await page.getByText(text.loadFailed, { exact: true }).waitFor();
                await capture('error');
                assert.equal(await items.count(), 0);
                mode = 'data';
                await page.getByRole('button', { name: text.retry, exact: true }).click();
                await items.first().waitFor();
                assert.equal(await items.count(), 20);

                mode = 'empty-page';
                await page.reload();
                await items.first().waitFor();
                await page
                    .getByRole('navigation', { name: text.pagination })
                    .getByRole('button', { name: '2', exact: true })
                    .click();
                await page.getByText(text.emptyPage, { exact: true }).waitFor();
                await capture('empty-page');
                await page
                    .getByRole('navigation', { name: text.pagination })
                    .getByRole('button', { name: '1', exact: true })
                    .click();
                await items.first().waitFor();
                assert.equal(await items.count(), 20);
                assert.deepEqual(errors, []);
                console.log(
                    `${locale} ${viewportName}: navigation, loading, pagination, refresh/retry, and empty states passed`,
                );
            } finally {
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
