import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/pagination.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const token = `test.${Buffer.from(JSON.stringify({ sub: 'pagination-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const building = {
    id: 'selected',
    user_id: 'pagination-owner',
    name: 'Selected building',
    address: null,
    latitude: null,
    longitude: null,
    created_at: '2026-10-14T10:00:00Z',
    updated_at: '2026-10-14T10:00:00Z',
};

async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for pagination recovery');
        await delay(10);
    }
}

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const kind of ['buildings', 'reconstructions']) {
        const context = await browser.newContext({ serviceWorkers: 'block' });
        try {
            await context.addInitScript((token) => {
                localStorage.setItem('access_token', token);
                localStorage.setItem('hud-language', 'en');
            }, token);
            await context.route('**/env.js', (route) =>
                route.fulfill({
                    contentType: 'application/javascript',
                    body: `window.env=${JSON.stringify({ API_URL: origin, API_PATH: '/pagination-api', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                }),
            );
            let total = 65;
            let hold = false;
            let release;
            const offsets = [];
            const searches = [];
            const listPath =
                kind === 'buildings' ? '/buildings' : '/buildings/selected/reconstructions';
            await context.route('**/pagination-api/**', async (route) => {
                const url = new URL(route.request().url());
                const path = url.pathname.replace('/pagination-api', '');
                if (path === '/user/me')
                    return route.fulfill({
                        json: { id: 'pagination-owner', terms_accepted: true },
                    });
                if (path === '/buildings/selected') return route.fulfill({ json: building });
                if (path === '/buildings/locations') return route.fulfill({ json: [] });
                if (path !== listPath) return route.fulfill({ json: { items: [], total: 0 } });

                assert.equal(url.searchParams.get('limit'), '20');
                const offset = Number(url.searchParams.get('offset'));
                offsets.push(offset);
                searches.push(url.searchParams.get('search'));
                if (hold)
                    await new Promise((resolve) => {
                        release = resolve;
                    });
                const items = Array.from(
                    { length: Math.min(20, Math.max(0, total - offset)) },
                    (_, i) => {
                        const id = String(offset + i).padStart(8, '0');
                        return kind === 'buildings'
                            ? {
                                  ...building,
                                  id,
                                  name: `Building ${id}`,
                                  latest_reconstruction: { id, status: 'running', progress: 0.5 },
                              }
                            : {
                                  id,
                                  building_id: building.id,
                                  status: 'waiting_for_upload',
                                  progress: 0.5,
                                  settings: {},
                                  splat_path: null,
                                  created_at: building.created_at,
                              };
                    },
                );
                return route.fulfill({ json: { items, total } });
            });
            const page = await context.newPage();
            await page.clock.install();
            const errors = [];
            page.on('pageerror', (error) => errors.push(error.message));
            await page.goto(
                `${origin}/#/${kind === 'buildings' ? 'library' : 'building/selected'}`,
            );
            const section = page.locator(
                `[aria-labelledby="${kind === 'buildings' ? 'my-buildings-title' : 'reconstructions-title'}"]`,
            );
            const navigation = section.getByRole('navigation');
            const rows = section.locator(
                kind === 'buildings'
                    ? '.my-buildings-list > .q-item'
                    : '.reconstructions-list > .q-expansion-item',
            );
            await rows.first().waitFor();
            assert.equal(await rows.count(), 20);

            if (kind === 'reconstructions') {
                const header = rows.first().locator('[aria-expanded]').first();
                await header.click();
                assert.equal(await header.getAttribute('aria-expanded'), 'true');
            }

            hold = true;
            await navigation.getByRole('button', { name: '4', exact: true }).click();
            await waitFor(() => release !== undefined);
            assert.equal(
                await navigation.getByRole('button', { name: '4', exact: true }).isDisabled(),
                true,
            );
            hold = false;
            release();
            await section
                .getByText(kind === 'buildings' ? 'Building 00000060' : /00000060/)
                .first()
                .waitFor();
            assert.equal(await rows.count(), 5);
            assert.equal(offsets.at(-1), 60);

            if (kind === 'buildings') {
                await page.getByRole('textbox', { name: 'Search buildings' }).fill('Hall');
                await page.clock.fastForward(300);
                await waitFor(() => offsets.at(-1) === 0 && searches.at(-1) === 'Hall');
                await section.getByText('Building 00000000', { exact: true }).waitFor();
            } else {
                await navigation.getByRole('button', { name: '1', exact: true }).click();
                await section
                    .getByText(/00000000/)
                    .first()
                    .waitFor();
                assert.equal(
                    await rows
                        .first()
                        .locator('[aria-expanded]')
                        .first()
                        .getAttribute('aria-expanded'),
                    'false',
                );
            }
            await navigation.getByRole('button', { name: '4', exact: true }).click();
            await section
                .getByText(kind === 'buildings' ? 'Building 00000060' : /00000060/)
                .first()
                .waitFor();

            total = 40;
            await page.clock.fastForward(5_000);
            await waitFor(() => offsets.at(-1) === 20);
            await section
                .getByText(kind === 'buildings' ? 'Building 00000020' : /00000020/)
                .first()
                .waitFor();
            assert.equal(await rows.count(), 20);
            assert.equal(
                await navigation.getByRole('button', { name: '3', exact: true }).count(),
                0,
            );

            total = 0;
            await page.clock.fastForward(5_000);
            await waitFor(() => offsets.at(-1) === 0);
            await rows.first().waitFor({ state: 'detached' });
            assert.equal(await navigation.count(), 0);
            assert.deepEqual(errors, []);
            console.log(
                `${kind}: exact page counts, loading bounds, polling, and shrinking totals passed`,
            );
        } finally {
            await context.close();
        }
    }
} finally {
    await browser.close();
}
