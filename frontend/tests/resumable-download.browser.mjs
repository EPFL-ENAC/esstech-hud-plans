import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

// node tests/resumable-download.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const token = `test.${Buffer.from(JSON.stringify({ sub: 'download-owner', exp: 4_000_000_000 })).toString('base64url')}.test`;
const payload = Buffer.from([1, 2, 3, 4, 5, 6]);
let scenario;

const server = createServer((request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.setHeader('Access-Control-Allow-Headers', 'Authorization, Range, If-Range');
    response.setHeader('Access-Control-Expose-Headers', 'ETag, Content-Length, Content-Range');
    if (request.method === 'OPTIONS') {
        response.writeHead(204).end();
        return;
    }
    const path = request.url;
    if (path.endsWith('/splat')) {
        scenario.requests.push({ range: request.headers.range, response });
        response.setHeader('Content-Type', 'application/octet-stream');
        response.setHeader('ETag', '"v1"');
        response.setHeader('Content-Length', payload.length);
        if (scenario.requests.length === 1) {
            if (scenario.stage !== 'headers') response.flushHeaders();
            if (scenario.stage === 'after one chunk') response.write(payload.subarray(0, 3));
            return;
        }
        response.end(payload);
        return;
    }
    response.setHeader('Content-Type', 'application/json');
    if (path === '/user/me') {
        response.end(JSON.stringify({ id: 'download-owner', terms_accepted: true }));
    } else if (path === '/buildings/locations') {
        response.end('[]');
    } else if (path === '/buildings/selected') {
        response.end(
            JSON.stringify({
                id: 'selected',
                name: 'Selected',
                user_id: 'download-owner',
                created_at: '2026-11-03T10:00:00Z',
                updated_at: '2026-11-03T10:00:00Z',
            }),
        );
    } else {
        response.end(JSON.stringify({ items: [], total: 0 }));
    }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const apiOrigin = `http://127.0.0.1:${server.address().port}`;

async function waitFor(condition) {
    const deadline = Date.now() + 10_000;
    while (!condition()) {
        assert.ok(Date.now() < deadline, 'Timed out waiting for the splat request');
        await delay(10);
    }
}

let browser;
try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    for (const persistent of [false, true]) {
        for (const stage of ['headers', 'first chunk', 'after one chunk']) {
            scenario = { stage, requests: [] };
            const context = await browser.newContext({ serviceWorkers: 'block' });
            try {
                await context.addInitScript(
                    ({ token, persistent }) => {
                        localStorage.setItem('access_token', token);
                        localStorage.setItem('hud-language', 'en');
                        if (!persistent) {
                            Object.defineProperty(navigator.storage, 'getDirectory', {
                                value: undefined,
                                configurable: true,
                            });
                        }
                    },
                    { token, persistent },
                );
                await context.route('**/env.js', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: `window.env=${JSON.stringify({ API_URL: apiOrigin, API_PATH: '', KEYCLOAK_ENDPOINT: origin, KEYCLOAK_REALM: 'test', KEYCLOAK_CLIENT_ID: 'test', SENTRY_RATE: '0' })};`,
                    }),
                );
                // Keep the test focused on transfer recovery, independent of WebGL/PLY parsing.
                await context.route('**/src/components/SplatRenderer.vue*', (route) =>
                    route.fulfill({
                        contentType: 'application/javascript',
                        body: 'export default { props: ["splatData"], emits: ["ready"], mounted() { this.$emit("ready"); }, render() { return null; } };',
                    }),
                );
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', (error) => errors.push(error.message));
                await page.clock.install();
                await page.goto(
                    `${origin}/#/building/selected/reconstruction/reconstruction/3d-plan`,
                );
                await waitFor(() => scenario.requests.length === 1);
                await page.getByText(/Downloading splats/).waitFor();
                assert.equal(
                    await page.evaluate(() => typeof navigator.storage.getDirectory === 'function'),
                    persistent,
                );
                // Let the received headers/chunk reach the browser before advancing its clock.
                if (stage !== 'headers') {
                    await page.waitForFunction(() =>
                        document.querySelector('[role="presentation"]')?.textContent.includes('/'),
                    );
                }
                await page.clock.fastForward(60_000);
                const retry = page.getByRole('button', { name: 'Retry', exact: true });
                await retry.waitFor();
                assert.equal(await retry.isEnabled(), true);
                await page
                    .getByText('Unable to load the splat. Please try again.', { exact: true })
                    .waitFor();
                assert.equal(await page.getByText(/Downloading splats/).count(), 0);
                await retry.click();
                await page
                    .getByRole('button', { name: 'Download 3D reconstruction (.ply)' })
                    .waitFor();
                assert.equal(scenario.requests.length, 2);
                assert.equal(await retry.count(), 0);
                assert.deepEqual(errors, []);
                console.log(`PASS ${stage}, persistent=${persistent}: error + RETRY + recovery`);
            } finally {
                await context.close();
            }
        }
    }
} finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
    );
}
