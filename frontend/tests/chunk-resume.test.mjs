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

const upload = await transpile('../src/lib/uploads/chunkUpload.ts', {
    "from 'boot/api'": `from '${STUB.api}'`,
    "from 'src/lib/auth'": `from '${STUB.auth}'`,
    "from 'src/lib/buildings'": `from '${STUB.buildings}'`,
});

const plan = [
    { index: 0, offset: 0, size: 4, sha256: 'a' },
    { index: 1, offset: 4, size: 4, sha256: 'b' },
    { index: 2, offset: 8, size: 4, sha256: 'c' },
    { index: 3, offset: 12, size: 4, sha256: 'd' },
    { index: 4, offset: 16, size: 2, sha256: 'e' },
];

test('put queue is the sorted subset of missing chunks', () => {
    assert.deepEqual(
        upload.computePutQueue(plan, [3, 1]).map((entry) => entry.index),
        [1, 3],
    );
    assert.deepEqual(
        upload.computePutQueue(plan, [0, 1, 2, 3, 4]).map((entry) => entry.index),
        [0, 1, 2, 3, 4],
    );
    assert.deepEqual(upload.computePutQueue(plan, []), []);
    assert.deepEqual(upload.computePutQueue(plan, [7]), []);
});

test('remaining indices exclude what a partial pass already sent', () => {
    assert.deepEqual(upload.remainingChunkIndices(plan, [0, 2]), [1, 3, 4]);
    assert.deepEqual(upload.remainingChunkIndices(plan, []), [0, 1, 2, 3, 4]);
    assert.deepEqual(upload.remainingChunkIndices(plan, [0, 1, 2, 3, 4]), []);
});

test('constants mirror the backend contract', () => {
    assert.equal(upload.UPLOAD_CHUNK_SIZE_BYTES, UPLOAD_CHUNK_BYTES);
    assert.equal(upload.SMALL_FILE_THRESHOLD, upload.UPLOAD_CHUNK_SIZE_BYTES);
    assert.equal(upload.PUT_CONCURRENCY, 2);
    assert.equal(upload.UPLOAD_RETRY_ATTEMPTS, 3);
});
