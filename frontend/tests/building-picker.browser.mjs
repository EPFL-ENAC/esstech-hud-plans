import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/building-picker.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9001';
const token = `test.${Buffer.from(JSON.stringify({ sub: 'picker-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const buildings = Array.from({ length: 241 }, (_, i) => ({
    id: `building-${i}`,
    name: `Building ${String(i).padStart(3, '0')}`,
    user_id: 'picker-owner',
    address: null,
    latitude: null,
    longitude: null,
    created_at: '2026-10-14T10:00:00Z',
    updated_at: '2026-10-14T10:00:00Z',
    latest_reconstruction: null,
}));
async function waitFor(condition) {
    const deadline = Date.now() + 12_000;
    while (!(await condition())) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for the building picker');
        await delay(25);
    }
}
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const [name, viewport] of Object.entries({
        mobile: { width: 390, height: 844 },
        desktop: { width: 1440, height: 1000 },
    })) {
        const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
        try {
            await context.addInitScript((token) => {
                localStorage.setItem('access_token', token);
                localStorage.setItem('hud-language', 'en');
            }, token);
            await context.route('**/env.js', (route) =>
                route.fulfill({
                    contentType: 'application/javascript',
                    body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/picker-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                }),
            );
            const offsets = [];
            const details = [];
            let releaseSelected;
            let releaseNext;
            let holdSelected = true;
            let failNext = true;
            let failInitial = false;
            let pending = 0;
            await context.route('**/picker-api/**', async (route) => {
                const url = new URL(route.request().url());
                const path = url.pathname.replace('/picker-api', '');
                if (path === '/user/me')
                    return route.fulfill({ json: { id: 'picker-owner', terms_accepted: true } });
                if (path === '/uploads/upload')
                    return route.fulfill({
                        json: {
                            id: 'upload',
                            filename: 'video.mp4',
                            status: 'uploaded',
                            uploaded_bytes: 100,
                            size_bytes: 100,
                            created_at: buildings[0].created_at,
                        },
                    });
                if (path === '/buildings') {
                    const offset = Number(url.searchParams.get('offset'));
                    assert.equal(url.searchParams.get('limit'), '20');
                    assert.equal(url.searchParams.get('sort_order'), 'desc');
                    offsets.push(offset);
                    pending++;
                    assert.equal(pending, 1, 'Page requests must never overlap');
                    if (offset === 20 && failNext)
                        await new Promise((resolve) => {
                            releaseNext = resolve;
                        });
                    pending--;
                    if (failInitial || (offset === 20 && failNext))
                        return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
                    return route.fulfill({
                        json: {
                            items: buildings.slice(offset, offset + 20),
                            total: buildings.length,
                        },
                    });
                }
                if (path.startsWith('/buildings/')) {
                    const id = path.split('/').pop();
                    details.push(id);
                    if (holdSelected) {
                        holdSelected = false;
                        await new Promise((resolve) => {
                            releaseSelected = resolve;
                        });
                    }
                    const building = buildings.find((building) => building.id === id);
                    return route.fulfill(
                        building
                            ? { json: building }
                            : { status: 404, json: { detail: 'Building not found' } },
                    );
                }
                throw new Error(`Unexpected request: ${path}`);
            });
            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', (error) => errors.push(error.message));
            const picker = page.locator('.reconstruction-form .q-select').first();
            const start = page.getByRole('button', {
                name: 'Start Processing (10-60min)',
                exact: true,
            });
            const listError = page.locator('.q-banner[role=alert]');
            const retry = listError.getByRole('button', { name: 'Retry', exact: true });
            const menu = page.getByRole('listbox');
            const scroll = async (end = true) => {
                // Let QSelect finish scrolling to the selected option when reopening.
                if (!end) await delay(250);
                await menu.evaluate((element, end) => {
                    element.scrollTop = end ? element.scrollHeight : 0;
                    element.dispatchEvent(new Event('scroll'));
                }, end);
                await delay(120);
            };
            await page.goto(
                `${origin}/#/reconstructions/from-upload/upload?buildingId=building-200`,
            );
            await waitFor(() => releaseSelected !== undefined && offsets.length === 1);
            assert.deepEqual(offsets, [0]);
            assert.equal(await start.isDisabled(), true);
            releaseSelected();
            await picker.getByText('Building 200', { exact: true }).waitFor();
            await waitFor(() => start.isEnabled());
            assert.deepEqual(details, ['building-200']);

            await picker.click();
            await menu.waitFor();
            await scroll();
            await waitFor(() => releaseNext !== undefined);
            await scroll();
            await scroll();
            assert.deepEqual(offsets, [0, 20]);
            releaseNext();
            await listError.waitFor();
            const failedRequests = offsets.length;
            await scroll();
            assert.equal(
                offsets.length,
                failedRequests,
                'Scroll must not automatically retry failures',
            );
            await page.keyboard.press('Escape');
            await waitFor(() => start.isEnabled());
            failNext = false;
            await retry.click();
            await waitFor(() => offsets.length === failedRequests + 1 && pending === 0);
            assert.deepEqual(offsets.slice(-2), [20, 20]);
            await listError.waitFor({ state: 'detached' });

            await picker.click();
            await menu.waitFor();
            for (let attempt = 0; offsets.at(-1) !== 240 && attempt < 30; attempt++) await scroll();
            await waitFor(() => offsets.at(-1) === 240 && pending === 0);
            await scroll();
            await menu.getByRole('option', { name: 'Building 240', exact: true }).waitFor();
            assert.ok(
                (await menu.getByRole('option').count()) < 100,
                'Only a virtual slice should render',
            );
            assert.deepEqual(offsets, [
                0,
                20,
                ...Array.from({ length: 12 }, (_, i) => (i + 1) * 20),
            ]);
            const finalCount = offsets.length;
            await scroll();
            assert.equal(offsets.length, finalCount);
            await menu.getByRole('option', { name: 'Building 240', exact: true }).click();
            await picker.getByText('Building 240', { exact: true }).waitFor();
            await waitFor(() => start.isEnabled());
            await picker.click();
            await menu.waitFor();
            await scroll(false);
            await menu.getByRole('option', { name: 'Create new', exact: true }).click();
            const draft = page.getByLabel('Building name (optional)', { exact: true });
            await draft.fill('Preserved draft');
            await picker.click();
            await menu.getByRole('option', { name: 'Building 000', exact: true }).click();
            await waitFor(() => start.isEnabled());
            await picker.click();
            await scroll(false);
            await menu.getByRole('option', { name: 'Create new', exact: true }).click();
            assert.equal(await draft.inputValue(), 'Preserved draft');
            assert.equal(offsets.length, finalCount, 'Reopening must reuse cached pages');

            await page.evaluate(async () => {
                await document
                    .querySelector('#q-app')
                    .__vue_app__.config.globalProperties.$router.push({
                        query: { buildingId: 'missing' },
                    });
            });
            await picker
                .getByText('Choose an available building or Create new.', { exact: true })
                .waitFor();
            assert.equal(await start.isDisabled(), true);

            failInitial = true;
            await page.reload();
            await listError.waitFor();
            assert.equal(await start.isDisabled(), true);
            failInitial = false;
            await retry.click();
            await waitFor(() => offsets.at(-1) === 0 && pending === 0);
            assert.deepEqual(errors, []);
            console.log(
                `${name}: lazy pages, selected lookup, retries, bounded DOM, cached reopening, and draft preservation passed`,
            );
        } finally {
            await context.close();
        }
    }
} finally {
    await browser.close();
}
