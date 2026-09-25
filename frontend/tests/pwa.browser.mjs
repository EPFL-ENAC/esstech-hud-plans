import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
// Use an existing Playwright installation; no extra project dependency is required.
// Usage: node tests/pwa.browser.mjs /absolute/path/to/playwright/index.mjs
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const frontend = fileURLToPath(new URL('../', import.meta.url));
let version = 1;
const types = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.css': 'text/css',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
};
function serve(mode) {
    const server = createServer(async (req, res) => {
        let path = new URL(req.url, 'http://localhost').pathname;
        if (path === '/') path = '/index.html';
        if (path.includes('..')) {
            res.writeHead(400).end();
            return;
        }
        try {
            let body = await readFile(join(frontend, 'dist', mode, path));
            if (path === '/sw.js')
                body = Buffer.concat([
                    body,
                    Buffer.from(`\nself.__hudSmokeVersion = ${version};\n`),
                ]);
            res.writeHead(200, {
                'Content-Type': types[extname(path)] || 'application/octet-stream',
                'Cache-Control': 'no-store',
            });
            res.end(body);
        } catch {
            res.writeHead(404).end();
        }
    });
    return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}
const servers = [await serve('pwa'), await serve('spa')];
const [pwaUrl, spaUrl] = servers.map((server) => `http://127.0.0.1:${server.address().port}`);
let browser;
try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    console.log('Chromium:', browser.version());
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const errors = [];
    const page = await context.newPage();
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`${pwaUrl}/#/login`);
    await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Install HUD Plans', exact: true }).waitFor();
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    const manifest = await page.evaluate(async () => (await fetch('/manifest.json')).json());
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.id, '/');
    for (const icon of manifest.icons) {
        const size = await page.evaluate(async (src) => {
            const image = new Image();
            image.src = src;
            await image.decode();
            return `${image.naturalWidth}x${image.naturalHeight}`;
        }, icon.src);
        assert.equal(size, icon.sizes);
    }
    await page.screenshot({ path: join(tmpdir(), 'hud-pwa-login.png') });
    console.log('PASS: online login, manifest, icons, installation control');
    await page.evaluate(() => {
        window.__retainedForm = { video: 'in-memory-sentinel' };
    });
    await context.setOffline(true);
    await page.getByRole('status').filter({ hasText: 'You’re offline' }).waitFor();
    assert.equal(await page.evaluate(() => window.__retainedForm.video), 'in-memory-sentinel');
    await context.setOffline(false);
    await page.waitForFunction(() => !document.querySelector('[role="status"]'));
    console.log('PASS: connectivity banner preserves mounted app state');
    for (const [locale, heading, button] of [
        ['en', 'You’re offline', 'Try again'],
        ['fr', 'Vous êtes hors ligne', 'Réessayer'],
        ['es', 'Sin conexión', 'Reintentar'],
    ]) {
        await page.evaluate((locale) => localStorage.setItem('hud-language', locale), locale);
        await context.setOffline(true);
        await page.reload();
        await page.getByRole('heading', { name: heading, exact: true }).waitFor();
        assert.equal(new URL(page.url()).hash, '#/login');
        await page.screenshot({ path: join(tmpdir(), `hud-pwa-offline-${locale}.png`) });
        await context.setOffline(false);
        await page.getByRole('button', { name: button, exact: true }).click();
        await page.waitForFunction(() => !!document.querySelector('.q-layout'));
    }
    console.log('PASS: offline launch, all three locales, retry, hash preservation');
    const cachedUrls = await page.evaluate(async () =>
        (
            await Promise.all(
                (await caches.keys()).map(async (key) =>
                    (await (await caches.open(key)).keys()).map((request) => request.url),
                ),
            )
        ).flat(),
    );
    assert.equal(cachedUrls.length, 1);
    assert.equal(new URL(cachedUrls[0]).pathname, '/offline.html');
    console.log('PASS: Cache Storage contains only offline.html');
    await page.evaluate(() => {
        window.__recordingSentinel = 'unchanged';
    });
    version = 2;
    await page.evaluate(async () => (await navigator.serviceWorker.getRegistration()).update());
    await page.waitForFunction(
        async () => !!(await navigator.serviceWorker.getRegistration()).waiting,
    );
    assert.equal(await page.evaluate(() => window.__recordingSentinel), 'unchanged');
    assert.equal(await context.serviceWorkers()[0].evaluate(() => self.__hudSmokeVersion), 1);
    await page.close();
    const reopened = await context.newPage();
    await reopened.goto(`${pwaUrl}/#/login`);
    await reopened.waitForFunction(async () => {
        const registration = await navigator.serviceWorker.getRegistration();
        return registration?.active && !registration.waiting && navigator.serviceWorker.controller;
    });
    const workerVersions = await Promise.all(
        context.serviceWorkers().map(async (worker) => {
            try {
                return await worker.evaluate(() => self.__hudSmokeVersion);
            } catch {
                return null;
            }
        }),
    );
    assert.ok(workerVersions.includes(2));
    console.log('PASS: second worker waits without reload and activates after closure');
    const spa = await context.newPage();
    await spa.goto(`${spaUrl}/#/login`);
    await spa.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
    assert.equal(await spa.locator('link[rel="manifest"]').count(), 0);
    assert.equal(
        await spa.getByRole('button', { name: 'Install HUD Plans', exact: true }).count(),
        0,
    );
    assert.equal(
        await spa.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length),
        0,
    );
    console.log('PASS: SPA has no manifest, install UI, or worker');
    assert.deepEqual(errors, []);
    console.log('PASS: no page JavaScript errors');
    await context.close();
} finally {
    await browser?.close();
    for (const server of servers) await new Promise((resolve) => server.close(resolve));
}
