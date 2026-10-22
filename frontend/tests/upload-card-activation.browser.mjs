import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/upload-card-activation.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9060';
const token = `test.${Buffer.from(JSON.stringify({ sub: 'card-user', exp: 4_000_000_000 })).toString('base64url')}.test`;
const newLabel = 'New reconstruction';
const rows = [
    {
        id: '00000000-0000-0000-0000-000000000001',
        user_id: 'card-user',
        name: 'TODO',
        description: '',
        filename: 'uploaded.mp4',
        size_bytes: 100,
        uploaded_bytes: 100,
        status: 'uploaded',
        created_at: '2026-10-18T10:00:00Z',
        uploaded_at: '2026-10-18T10:01:00Z',
    },
    {
        id: '00000000-0000-0000-0000-000000000002',
        user_id: 'card-user',
        name: 'TODO',
        description: '',
        filename: 'failed.mp4',
        size_bytes: 100,
        uploaded_bytes: 0,
        status: 'failed',
        created_at: '2026-10-18T10:00:00Z',
        uploaded_at: null,
    },
    {
        id: '00000000-0000-0000-0000-000000000003',
        user_id: 'card-user',
        name: 'TODO',
        description: '',
        filename: 'pending.mp4',
        size_bytes: 100,
        uploaded_bytes: 40,
        status: 'pending',
        created_at: '2026-10-18T10:00:00Z',
        uploaded_at: null,
    },
];

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [size, viewport] of Object.entries({
        mobile: { width: 390, height: 844 },
        desktop: { width: 1440, height: 1000 },
    })) {
        const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
        try {
            await context.addInitScript(
                ({ token }) => {
                    localStorage.setItem('access_token', token);
                    localStorage.setItem('hud-language', 'en');
                    localStorage.setItem('hud-hide-video-tips', 'true');
                },
                { token },
            );
            await context.route('**/env.js', (route) =>
                route.fulfill({
                    contentType: 'application/javascript',
                    body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/card-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                }),
            );
            await context.route('**/card-api/**', (route) => {
                const request = route.request();
                const path = new URL(request.url()).pathname.replace('/card-api', '');
                assert.equal(request.headers().authorization, `Bearer ${token}`);
                if (path === '/user/me')
                    return route.fulfill({ json: { id: 'card-user', terms_accepted: true } });
                if (path === '/uploads') return route.fulfill({ json: rows });
                if (path.startsWith('/uploads/')) {
                    const row = rows.find((row) => row.id === path.split('/').pop());
                    return route.fulfill(row ? { json: row } : { status: 404, json: {} });
                }
                return route.fulfill({ json: [] });
            });
            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', (error) => errors.push(error.message));

            async function installPushSpy() {
                await page.evaluate(() => {
                    window.__pushes = [];
                    if (window.__pushSpyInstalled) return;
                    window.__pushSpyInstalled = true;
                    const router =
                        document.querySelector('#q-app').__vue_app__.config.globalProperties
                            .$router;
                    const push = router.push.bind(router);
                    router.push = (...args) => {
                        window.__pushes.push(args[0]);
                        return push(...args);
                    };
                });
            }
            const pushNames = () =>
                page.evaluate(() => window.__pushes.map((target) => target?.name ?? target));
            async function openPicker() {
                await page.goto(`${origin}/#/reconstructions/from-upload`);
                await page.getByText('uploaded.mp4', { exact: true }).waitFor();
                await installPushSpy();
            }
            const listItems = () => page.locator('.uploads-list').getByRole('listitem');
            const row = (filename) => listItems().filter({ hasText: filename });
            const expectSinglePush = async (uploadId) => {
                await page.waitForURL(`**/#/reconstructions/from-upload/${uploadId}`);
                assert.deepEqual(await pushNames(), ['reconstruction-from-upload']);
            };

            await openPicker();
            assert.equal(await listItems().count(), 3);
            assert.equal(await row('failed.mp4').getByRole('link', { name: newLabel }).count(), 0);
            assert.equal(
                await row('uploaded.mp4').getByRole('link', { name: newLabel }).count(),
                1,
            );

            await row('uploaded.mp4').locator('.upload-text').first().click();
            await expectSinglePush(rows[0].id);

            await openPicker();
            await row('uploaded.mp4').getByRole('link', { name: newLabel }).click();
            await expectSinglePush(rows[0].id);

            await openPicker();
            await row('uploaded.mp4').focus();
            await page.keyboard.press('Enter');
            await expectSinglePush(rows[0].id);

            await openPicker();
            await row('uploaded.mp4').focus();
            await page.keyboard.press('Space');
            await expectSinglePush(rows[0].id);

            await openPicker();
            const failed = row('failed.mp4');
            assert.equal(await failed.getAttribute('tabindex'), null);
            await failed.locator('.upload-text').first().click();
            await delay(500);
            assert.equal(new URL(page.url()).hash, '#/reconstructions/from-upload');
            assert.deepEqual(await pushNames(), []);

            await openPicker();
            await row('pending.mp4').locator('.upload-text').first().click();
            await expectSinglePush(rows[2].id);

            await page.goto(`${origin}/#/uploads`);
            await page.getByText('uploaded.mp4', { exact: true }).waitFor();
            await installPushSpy();
            await row('uploaded.mp4').locator('.upload-text').first().click();
            await delay(500);
            assert.equal(new URL(page.url()).hash, '#/uploads');
            assert.deepEqual(await pushNames(), []);

            assert.deepEqual(errors, []);
            console.log(`${size}: card, plus, keyboard, failed row, plain uploads list passed`);
        } finally {
            await context.close();
        }
    }
} finally {
    await browser.close();
}
