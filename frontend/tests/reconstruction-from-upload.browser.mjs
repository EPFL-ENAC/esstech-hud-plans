import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

// node tests/reconstruction-from-upload.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9050';
const screenshots = join(tmpdir(), 'hud-reconstruction-from-upload');
await mkdir(screenshots, { recursive: true });
const token = `test.${Buffer.from(JSON.stringify({ sub: 'reconstruction-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
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
            const rows = Array.from({ length: 25 }, (_, index) => ({
                id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
                user_id: 'reconstruction-owner',
                name: 'TODO',
                description: '',
                filename:
                    index === 0 ? `${'long-video-name-'.repeat(8)}.mp4` : `video-${index + 1}.mp4`,
                size_bytes: 1234567,
                status: index === 0 ? 'pending' : index === 2 ? 'failed' : 'uploaded',
                created_at: '2026-10-18T10:00:00Z',
                uploaded_at: index === 0 || index === 2 ? null : '2026-10-18T10:01:00Z',
            }));
            const submissions = [];
            const details = [];
            let listMode = 'data';
            let detailError = false;
            let reconstruction;
            let destination;
            const building = (id, name = 'Existing building') => ({
                id,
                name,
                user_id: 'reconstruction-owner',
                address: null,
                latitude: null,
                longitude: null,
                created_at: '2026-10-18T10:00:00Z',
                updated_at: '2026-10-18T10:00:00Z',
                latest_reconstruction: reconstruction?.building_id === id ? reconstruction : null,
            });
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
                        body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/from-upload-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                await context.route('**/from-upload-api/**', async (route) => {
                    const request = route.request();
                    const url = new URL(request.url());
                    const path = url.pathname.replace('/from-upload-api', '');
                    assert.equal(request.headers().authorization, `Bearer ${token}`);
                    assert.ok(
                        !path.startsWith('/tus/'),
                        'Stored uploads must never transfer again',
                    );
                    if (path === '/user/me')
                        return route.fulfill({
                            json: { id: 'reconstruction-owner', terms_accepted: true },
                        });
                    if (path === '/uploads') {
                        assert.equal(url.searchParams.get('limit'), '21');
                        assert.equal(url.searchParams.get('sort_order'), 'desc');
                        if (listMode === 'error')
                            return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
                        const offset = Number(url.searchParams.get('offset'));
                        return route.fulfill({
                            json: listMode === 'empty' ? [] : rows.slice(offset, offset + 21),
                        });
                    }
                    if (path.startsWith('/uploads/')) {
                        const id = decodeURIComponent(path.split('/').pop());
                        details.push(id);
                        if (detailError)
                            return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
                        const row = rows.find((row) => row.id === id);
                        return route.fulfill(
                            row
                                ? { json: row }
                                : {
                                      status: id === 'malformed' ? 422 : 404,
                                      json: { detail: 'Unavailable' },
                                  },
                        );
                    }
                    if (request.method() === 'POST') {
                        const body = request.postDataJSON();
                        assert.ok(path.endsWith('/from-upload'));
                        const upload = rows.find((row) => row.id === body.upload_id);
                        assert.ok(upload && upload.status !== 'failed');
                        submissions.push({ path, body });
                        destination = building(
                            body.building ? 'created' : 'existing',
                            body.building?.name,
                        );
                        reconstruction = {
                            id: `reconstruction-${submissions.length}`,
                            building_id: destination.id,
                            status:
                                upload.status === 'pending' ? 'waiting_for_upload' : 'scheduled',
                            progress: 0,
                            settings: body.settings,
                            error_message: null,
                            created_at: '2026-10-18T10:00:00Z',
                            updated_at: '2026-10-18T10:00:00Z',
                            splat_path: null,
                            input_video_path: null,
                        };
                        return route.fulfill({
                            status: 202,
                            json: body.building
                                ? { building: destination, reconstruction }
                                : reconstruction,
                        });
                    }
                    if (path === '/buildings')
                        return route.fulfill({
                            json: [
                                building('existing'),
                                ...(destination?.id === 'created'
                                    ? [building('created', destination.name)]
                                    : []),
                            ],
                        });
                    if (/^\/buildings\/[^/]+$/.test(path))
                        return route.fulfill({
                            json: building(path.split('/').pop(), destination?.name),
                        });
                    if (path.endsWith('/reconstructions'))
                        return route.fulfill({ json: reconstruction ? [reconstruction] : [] });
                    return route.fulfill({ json: [] });
                });
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                const goto = async (path) => {
                    await page.goto(`${origin}/#${path}`);
                    await page.waitForFunction((expected) => {
                        const router =
                            document.querySelector('#q-app')?.__vue_app__?.config.globalProperties
                                .$router;
                        return router?.currentRoute.value.fullPath === expected;
                    }, path);
                };
                const start = () =>
                    page.getByRole('button', { name: text.capture.startProcessing, exact: true });
                const ready = () =>
                    page.waitForFunction(() => {
                        const button = document.querySelector('.reconstruction-form > .q-btn');
                        return button && !button.disabled;
                    });
                const fits = async () =>
                    assert.ok(
                        await page.evaluate(
                            () => document.documentElement.scrollWidth <= innerWidth,
                        ),
                    );

                // The shared list has no action buttons on the uploads page.
                await goto('/uploads');
                await page.locator('.uploads-list [role=listitem]').first().waitFor();
                assert.equal(await page.locator('.uploads-list a').count(), 0);
                await goto('/reconstructions/from-upload');
                const items = page.locator('.uploads-list [role=listitem]');
                await items.first().waitFor();
                assert.equal(await items.count(), 20);
                await page.locator('.uploads-list a').first().waitFor();
                assert.equal(await page.locator('.uploads-list a').count(), 20);
                assert.equal(await page.locator('.uploads-list .q-item--clickable').count(), 0);
                await page.getByText(rows[0].filename, { exact: true }).click();
                assert.ok(page.url().endsWith('/reconstructions/from-upload'));
                await fits();
                await page.screenshot({ path: join(screenshots, `${locale}-${size}-list.png`) });
                await page.getByRole('button', { name: '2', exact: true }).click();
                await page.getByText(rows[20].filename, { exact: true }).waitFor();
                assert.equal(await items.count(), 5);
                await page.getByRole('button', { name: '1', exact: true }).click();
                await page.getByText(rows[0].filename, { exact: true }).waitFor();
                const action = items
                    .first()
                    .getByRole('link', { name: text.reconstructions.new, exact: true });
                await action.focus();
                await page.keyboard.press('Enter');
                await page.waitForURL(`**/reconstructions/from-upload/${rows[0].id}`);
                await ready();
                assert.equal(details.at(-1), rows[0].id);
                assert.equal(await page.locator('input[type=file], video').count(), 0);
                const name = page.getByLabel(text.buildings.fields.name, { exact: true });
                await name.fill('Preserved building');
                await page.reload();
                await ready();
                await name.fill('Preserved building');
                detailError = true;
                await page.getByRole('button', { name: text.uploads.refresh, exact: true }).click();
                await page
                    .getByText(text.reconstructions.fromUpload.loadFailed, { exact: true })
                    .waitFor();
                assert.equal(await name.inputValue(), 'Preserved building');
                assert.equal(await start().isDisabled(), true);
                detailError = false;
                await page.getByRole('button', { name: text.common.retry, exact: true }).click();
                await ready();
                assert.equal(await name.inputValue(), 'Preserved building');
                await fits();
                await page.screenshot({ path: join(screenshots, `${locale}-${size}-form.png`) });

                // Navigation failure retains the submitted destination and prevents duplicates.
                await page.evaluate(() => {
                    const router =
                        document.querySelector('#q-app').__vue_app__.config.globalProperties
                            .$router;
                    window.removeSubmissionGuard = router.beforeEach((to) =>
                        to.path.startsWith('/building/') ? false : undefined,
                    );
                });
                await start().click();
                await page
                    .getByRole('button', { name: text.buildings.view, exact: true })
                    .waitFor();
                assert.equal(submissions.length, 1);
                assert.equal(submissions[0].path, '/buildings/from-reconstruction/from-upload');
                assert.equal(submissions[0].body.upload_id, rows[0].id);
                assert.equal(submissions[0].body.building.name, 'Preserved building');
                assert.equal(submissions[0].body.settings.ffmpeg.fps, 4);
                assert.equal(await start().isDisabled(), true);
                await page.evaluate(() => window.removeSubmissionGuard());
                await page.getByRole('button', { name: text.buildings.view, exact: true }).click();
                await page.waitForURL('**/#/building/created');
                await page
                    .getByText(text.reconstructions.status.waiting_for_upload, { exact: true })
                    .first()
                    .waitFor();
                reconstruction.status = 'scheduled';
                await page
                    .getByText(text.reconstructions.status.scheduled, { exact: true })
                    .first()
                    .waitFor({ timeout: 12_000 });

                // A completed upload can instead target an existing building.
                await goto(`/reconstructions/from-upload/${rows[1].id}`);
                await ready();
                await page.locator('.reconstruction-form .q-select').first().click();
                await page
                    .getByRole('option')
                    .getByText('Existing building', { exact: true })
                    .click();
                await ready();
                await start().click();
                await page.waitForURL('**/#/building/existing');
                assert.equal(submissions.length, 2);
                assert.equal(
                    submissions[1].path,
                    '/buildings/existing/reconstructions/from-upload',
                );
                assert.equal(submissions[1].body.upload_id, rows[1].id);
                assert.equal(submissions[1].body.building, undefined);

                await goto(`/reconstructions/from-upload/${rows[2].id}`);
                await page
                    .getByText(text.reconstructions.fromUpload.failedUpload, { exact: true })
                    .waitFor();
                assert.equal(await start().isDisabled(), true);
                for (const id of ['missing', 'malformed']) {
                    await goto(`/reconstructions/from-upload/${id}`);
                    await page
                        .getByText(text.reconstructions.fromUpload.unavailable, { exact: true })
                        .waitFor();
                    assert.equal(await page.locator('.reconstruction-form').count(), 0);
                }
                assert.equal(submissions.length, 2);
                await goto('/reconstructions/from-upload');
                await items.first().waitFor();
                listMode = 'error';
                await page.getByRole('button', { name: text.uploads.refresh, exact: true }).click();
                await page.getByText(text.uploads.refreshFailed, { exact: true }).waitFor();
                assert.equal(await items.count(), 20);
                listMode = 'empty';
                await page.getByRole('button', { name: text.common.retry, exact: true }).click();
                await page.getByText(text.uploads.empty, { exact: true }).waitFor();
                assert.deepEqual(errors, []);
                console.log(
                    `${locale} ${size}: list slot, direct detail, refresh, new/existing submission, waiting poll, failed/unavailable uploads passed`,
                );
            } finally {
                await context.close();
            }
        }
    }
} finally {
    await browser.close();
}
