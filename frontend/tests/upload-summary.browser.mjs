import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

// node tests/upload-summary.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const owner = 'summary-owner';
const token = `test.${Buffer.from(JSON.stringify({ sub: owner, exp: 4_000_000_000 })).toString('base64url')}.test`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ serviceWorkers: 'block' });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
const errors = [];
const detailRequests = [];
let failLinkedFetch = true;
page.on('pageerror', (error) => errors.push(error.message));

try {
    await context.addInitScript((accessToken) => {
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('hud-language', 'en');
        Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    }, token);
    await context.route('**/env.js', (route) =>
        route.fulfill({
            contentType: 'application/javascript',
            body: `window.env=${JSON.stringify({
                API_URL: origin,
                API_PATH: '/summary-api',
                KEYCLOAK_ENDPOINT: origin,
                KEYCLOAK_REALM: 'test',
                KEYCLOAK_CLIENT_ID: 'test',
                SENTRY_RATE: '0',
            })};`,
        }),
    );
    await context.route('**/summary-api/**', (route) => {
        const path = new URL(route.request().url()).pathname.replace('/summary-api', '');
        if (path === '/user/me')
            return route.fulfill({ json: { id: owner, terms_accepted: true } });
        if (!path.startsWith('/uploads/')) return route.fulfill({ json: { items: [], total: 0 } });

        const id = path.split('/').at(-1);
        detailRequests.push(id);
        if (id === 'linked' && failLinkedFetch)
            return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });

        return route.fulfill({
            json: {
                id,
                user_id: owner,
                filename: `${id}.mp4`,
                size_bytes: 100,
                uploaded_bytes: id === 'direct' ? 100 : 40,
                status: id === 'direct' ? 'uploaded' : 'pending',
            },
        });
    });

    await page.goto(`${origin}/#/uploads`);
    await page.waitForFunction(() => document.querySelector('#q-app')?.__vue_app__);
    await page.evaluate(async (ownerId) => {
        const { LocalUploadsRegistry } = await import('/src/lib/localUploadsRegistry.ts');
        const { VideoUploadTask } = await import('/src/lib/videoUploadTask.ts');
        const { useNetworkDependentTasks } = await import('/src/stores/networkDependentTasks.ts');
        const { default: UploadSummary } = await import('/src/components/UploadSummary.vue');
        const source = await fetch('/src/composables/useUploadSummary.ts').then((response) =>
            response.text(),
        );
        const vueUrl = source.match(/from ["']([^"']*\/vue\.js[^"']*)["']/)[1];
        const { h, render } = await import(vueUrl);
        const app = document.querySelector('#q-app').__vue_app__;
        const queue = app.runWithContext(useNetworkDependentTasks);
        const uploads = new LocalUploadsRegistry();
        const file = new File(['video'], 'backup.mp4', { type: 'video/mp4' });
        const backup = await uploads.create(ownerId, file);
        const task = new VideoUploadTask({
            ownerId,
            label: file.name,
            localUploadId: backup.id,
            uploads,
        });
        await queue.submit(task, { waitForFirstTry: false });

        const container = document.createElement('div');
        container.id = 'upload-summary-test';
        document.body.append(container);
        function show(uploadReference) {
            const vnode = h(UploadSummary, { uploadReference });
            vnode.appContext = app._context;
            render(vnode, container);
        }

        show({ localUploadId: backup.id });
        window.summaryHarness = {
            show,
            assignRemote: () =>
                uploads.setRemote(ownerId, backup.id, {
                    uploadId: 'linked',
                    uploadUrl: `${location.origin}/summary-api/tus/linked`,
                }),
            dispose() {
                render(null, container);
                container.remove();
            },
        };
    }, owner);

    const container = page.locator('#upload-summary-test');
    const summary = container.locator('.upload-summary');
    await summary.getByText('backup.mp4', { exact: true }).waitFor();
    await summary.getByText('Queued', { exact: true }).waitFor();
    assert.deepEqual(detailRequests, []);

    await page.evaluate(() => window.summaryHarness.assignRemote());
    await container.getByText('Could not load this upload. Please try again.').waitFor();
    assert.equal(await summary.getByText('backup.mp4', { exact: true }).isVisible(), true);
    assert.deepEqual(detailRequests, ['linked']);

    failLinkedFetch = false;
    await container.getByRole('button', { name: 'Retry', exact: true }).click();
    await summary.getByText('linked.mp4', { exact: true }).waitFor();
    await summary.getByText('Pending', { exact: true }).waitFor();
    const progress = summary.getByRole('progressbar');
    assert.equal(await progress.getAttribute('aria-valuenow'), '0.4');

    await page.evaluate(() => window.summaryHarness.show({ uploadId: 'direct' }));
    await summary.getByText('direct.mp4', { exact: true }).waitFor();
    await summary.getByText('Uploaded', { exact: true }).waitFor();
    assert.equal(await progress.count(), 0);
    assert.equal(detailRequests.at(-1), 'direct');
    await page.evaluate(() => window.summaryHarness.dispose());
    assert.deepEqual(errors, []);
    console.log('Upload summary shows queued backup, server retry, progress, and a direct upload.');
} finally {
    await browser.close();
}
