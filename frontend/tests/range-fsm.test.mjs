import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const UPLOAD_CHUNK_BYTES = 8_388_608;

const STUB = {
    api: 'data:text/javascript,export const baseUrl = "";',
    auth: 'data:text/javascript,export const authFetch = function () {};',
    buildings:
        'data:text/javascript,export class ApiError extends Error { constructor(message, status, body) { super(message); this.status = status; this.body = body; } }',
    fetchProgress:
        'data:text/javascript,export async function downloadWithProgress() {}; export function formatMb() {}',
    localTransfers:
        'data:text/javascript,export const probeIndexedDb = async function() { return false; }; export const requestPersistentStorage = async function() {}; export const saveDownloadChunk = async function() {}; export const saveDownloadMeta = async function() {}; export const getDownloadMeta = async function() { return null; }; export const getDownloadChunk = async function() { return null; }; export const deleteDownloadData = async function() {}; export const downloadChunkId = function(key, index) { return key + ":" + index; };',
};

function stubModule(code) {
    return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

async function transpile(path, replacements) {
    const { outputText } = ts.transpileModule(
        readFileSync(new URL(path, import.meta.url), 'utf8'),
        { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
    );
    let source = outputText;
    for (const [from, to] of Object.entries(replacements)) {
        source = source.replaceAll(from, to);
    }
    return stubModule(source);
}

const download = await transpile('../src/lib/downloads/chunkedDownload.ts', {
    "from 'boot/api'": `from '${STUB.api}'`,
    "from 'src/lib/auth'": `from '${STUB.auth}'`,
    "from 'src/lib/buildings'": `from '${STUB.buildings}'`,
    "from 'src/lib/utils/fetchProgress'": `from '${STUB.fetchProgress}'`,
    "from '../localTransfers'": `from '${STUB.localTransfers}'`,
});

test('range decisions append on 206, reset on 200 and restart on 416', () => {
    assert.equal(download.nextRangeDecision(206), 'append');
    assert.equal(download.nextRangeDecision(200), 'reset');
    assert.equal(download.nextRangeDecision(416), 'restart');
    assert.equal(download.nextRangeDecision(404), 'error');
    assert.equal(download.nextRangeDecision(500), 'error');
});

test('range header uses one closed range and covers the last part', () => {
    assert.equal(download.rangeHeaderValue(0, 0), `bytes=0-${UPLOAD_CHUNK_BYTES - 1}`);
    assert.equal(
        download.rangeHeaderValue(UPLOAD_CHUNK_BYTES, UPLOAD_CHUNK_BYTES * 3),
        `bytes=${UPLOAD_CHUNK_BYTES}-${UPLOAD_CHUNK_BYTES * 2 - 1}`,
    );
    assert.equal(
        download.rangeHeaderValue(UPLOAD_CHUNK_BYTES * 2, UPLOAD_CHUNK_BYTES * 3 - 100),
        `bytes=${UPLOAD_CHUNK_BYTES * 2}-${UPLOAD_CHUNK_BYTES * 3 - 101}`,
    );
    assert.equal(
        download.rangeHeaderValue(UPLOAD_CHUNK_BYTES * 2, UPLOAD_CHUNK_BYTES * 2 + 5),
        `bytes=${UPLOAD_CHUNK_BYTES * 2}-${UPLOAD_CHUNK_BYTES * 2 + 4}`,
    );
});

test('content range parser reads start, end, total, and rejects garbage', () => {
    const info = download.parseContentRange('bytes 8388608-16777215/20000000');
    assert.deepEqual(info, { start: 8_388_608, end: 16_777_215, total: 20_000_000 });
    assert.deepEqual(download.parseContentRange('bytes 0-5/*'), {
        start: 0,
        end: 5,
        total: 0,
    });
    assert.equal(download.parseContentRange(null), null);
    assert.equal(download.parseContentRange('items 1-5/10'), null);
});

test('chunk index derives from the byte offset', () => {
    assert.equal(download.chunkIndexForOffset(0), 0);
    assert.equal(download.chunkIndexForOffset(UPLOAD_CHUNK_BYTES - 1), 0);
    assert.equal(download.chunkIndexForOffset(UPLOAD_CHUNK_BYTES), 1);
    assert.equal(download.chunkIndexForOffset(UPLOAD_CHUNK_BYTES * 3 + 7), 3);
});
