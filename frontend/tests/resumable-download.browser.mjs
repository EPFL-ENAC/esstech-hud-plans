import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';

// node tests/resumable-download.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const payload = Buffer.from([1, 2, 3, 4, 5, 6]);
const requests = [];
const server = createServer((request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.setHeader('Access-Control-Allow-Headers', 'Authorization, Range, If-Range');
    response.setHeader('Access-Control-Expose-Headers', 'ETag, Content-Length, Content-Range');
    if (request.method === 'OPTIONS') return response.writeHead(204).end();
    requests.push({ path: request.url, range: request.headers.range });
    response.setHeader('ETag', '"v1"');
    if (request.url === '/blocked') return response.flushHeaders();
    const start = request.headers.range
        ? Number(request.headers.range.match(/bytes=(\d+)-/)[1])
        : 0;
    if (start > 0) {
        response.statusCode = 206;
        response.setHeader(
            'Content-Range',
            `bytes ${start}-${payload.length - 1}/${payload.length}`,
        );
    }
    response.setHeader('Content-Length', payload.length - start);
    response.end(payload.subarray(start));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const apiOrigin = `http://127.0.0.1:${server.address().port}`;
let browser;

async function initialize(page) {
    // Import the new library directly; no application consumer is needed.
    await page.goto(origin);
    await page.evaluate(async () => {
        window.downloadLibrary = await import('/src/lib/resumableDownload/index.ts');
    });
}

try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const first = await context.newPage();
    await initialize(first);
    const url = `${apiOrigin}/file`;
    await first.evaluate(async (url) => {
        const download = await window.downloadLibrary.ResumableDownload.open(url);
        const original = Blob.prototype.arrayBuffer;
        Blob.prototype.arrayBuffer = () => {
            throw new Error('Unexpected full-file materialization');
        };
        try {
            const file = await download.download();
            if (!(file instanceof File) || file.size !== 6)
                throw new Error('Expected the OPFS File');
        } finally {
            Blob.prototype.arrayBuffer = original;
        }
    }, url);
    assert.equal(requests.length, 1);
    await initialize(first); // Reload the document and its library instances.
    assert.deepEqual(
        await first.evaluate(async (url) => {
            const download = await window.downloadLibrary.ResumableDownload.open(url);
            const file = await download.download();
            return [...new Uint8Array(await file.arrayBuffer())];
        }, url),
        [...payload],
    );
    assert.equal(requests.length, 1);

    const second = await context.newPage();
    await initialize(second);
    const blockedUrl = `${apiOrigin}/blocked`;
    await second.evaluate(async (url) => {
        window.olderDownload = await window.downloadLibrary.ResumableDownload.open(url);
    }, blockedUrl);
    await first.evaluate(async (url) => {
        window.controller = new AbortController();
        const download = await window.downloadLibrary.ResumableDownload.open(url);
        window.activeDownload = download.download({ signal: window.controller.signal }).then(
            () => 'unexpected success',
            (error) => error.name,
        );
    }, blockedUrl);
    await first.waitForFunction(async (url) => {
        const { held } = await navigator.locks.query();
        return held.some((lock) => lock.name.endsWith(url));
    }, blockedUrl);
    assert.match(
        await second.evaluate(async () => {
            try {
                await window.olderDownload.download();
                return 'unexpected success';
            } catch (error) {
                return error.message;
            }
        }),
        /already being downloaded/,
    );
    assert.match(
        await second.evaluate(async () => {
            try {
                await window.olderDownload.reset();
                return 'unexpected success';
            } catch (error) {
                return error.message;
            }
        }),
        /already being downloaded/,
    );
    assert.equal(
        await first.evaluate(async () => {
            window.controller.abort();
            return window.activeDownload;
        }),
        'AbortError',
    );

    // Seed an actual partial file and checkpoint, then verify HTTP Range recovery.
    await first.evaluate(async (url) => {
        const { DiskDownloadFile, DownloadsDatabase } = window.downloadLibrary;
        const file = await DiskDownloadFile.open(url);
        await file.append(new Uint8Array([1, 2, 3]));
        await file.flush();
        await new DownloadsDatabase().save({
            url,
            committedBytes: 3,
            totalBytes: 6,
            etag: '"v1"',
            complete: false,
        });
    }, blockedUrl);
    // The older instance must reread persisted state after acquiring the lock.
    // Use /file for the resumed response, leaving the original URL as the cache key.
    await context.route(`${apiOrigin}/blocked`, (route) =>
        route.continue({ url: `${apiOrigin}/file` }),
    );
    assert.deepEqual(
        await second.evaluate(async () => {
            const file = await window.olderDownload.download();
            return [...new Uint8Array(await file.arrayBuffer())];
        }),
        [...payload],
    );
    assert.equal(requests.at(-1).range, 'bytes=3-');
    await first.evaluate(async (url) => {
        await (await window.downloadLibrary.ResumableDownload.open(url)).reset();
    }, url);
    assert.equal(
        await first.evaluate(async () => {
            const root = await navigator.storage.getDirectory();
            const directory = await root.getDirectoryHandle('resumable-downloads');
            const entries = [];
            for await (const entry of directory.values()) entries.push(entry);
            return entries.length;
        }),
        1,
    ); // Only the other URL remains.
    console.log(
        'PASS OPFS retention, reload reuse, direct File reads, cross-tab locks, resume, and reset',
    );
    await context.close();
} finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
}
