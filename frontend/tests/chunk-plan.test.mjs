import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const CHUNK_SIZE = 4;
const UPLOAD_CHUNK_BYTES = 8_388_608;

function stubModule(code) {
    return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

async function transpile(path) {
    const { outputText } = ts.transpileModule(
        readFileSync(new URL(path, import.meta.url), 'utf8'),
        { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
    );
    return stubModule(outputText);
}

const digest = await transpile('../src/lib/uploads/fileDigest.ts');

test('chunk math splits sizes and keeps the last chunk partial', () => {
    assert.equal(digest.chunkCountForSize(0, CHUNK_SIZE), 0);
    assert.equal(digest.chunkCountForSize(8, CHUNK_SIZE), 2);
    assert.equal(digest.chunkCountForSize(10, CHUNK_SIZE), 3);
    assert.equal(digest.chunkSizeForIndex(0, 10, CHUNK_SIZE), CHUNK_SIZE);
    assert.equal(digest.chunkSizeForIndex(1, 10, CHUNK_SIZE), CHUNK_SIZE);
    assert.equal(digest.chunkSizeForIndex(2, 10, CHUNK_SIZE), 2);
    assert.throws(() => digest.chunkCountForSize(10, 0));
});

test('chunk plan covers every byte with correct offsets and digests', async () => {
    const bytes = Uint8Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    const file = new File([bytes], 'test.mp4', { lastModified: 42 });
    const plan = await digest.buildChunkPlan(file, CHUNK_SIZE);

    assert.equal(plan.length, 3);
    assert.deepEqual(
        plan.map((entry) => [entry.index, entry.offset, entry.size]),
        [
            [0, 0, CHUNK_SIZE],
            [1, CHUNK_SIZE, CHUNK_SIZE],
            [2, 2 * CHUNK_SIZE, 2],
        ],
    );
    const expectedFirst = await digest.digestBytes(bytes.slice(0, CHUNK_SIZE));
    const expectedLast = await digest.digestBytes(bytes.slice(2 * CHUNK_SIZE));
    assert.equal(plan[0].sha256, expectedFirst);
    assert.equal(plan[2].sha256, expectedLast);
});

test('file fingerprint guard rejects a re-selected file', () => {
    const file = new File([new Uint8Array(4)], 'test.mp4', { lastModified: 42 });
    const fingerprint = digest.makeFileFingerprint(file);
    assert.deepEqual(fingerprint, { name: 'test.mp4', size: 4, lastModified: 42 });
    assert.equal(digest.fingerprintMatches(file, fingerprint), true);
    const changed = new File([new Uint8Array(4)], 'test.mp4', { lastModified: 43 });
    assert.equal(digest.fingerprintMatches(changed, fingerprint), false);
    const renamed = new File([new Uint8Array(4)], 'other.mp4', { lastModified: 42 });
    assert.equal(digest.fingerprintMatches(renamed, fingerprint), false);
});

test('single chunk digest of the whole file matches the plan', async () => {
    const bytes = Uint8Array.from([1, 2, 3, 4, 5, 6, 7, 8]);
    const file = new File([bytes], 'one.mp4', { lastModified: 1 });
    const plan = await digest.buildChunkPlan(file, UPLOAD_CHUNK_BYTES);
    assert.equal(plan.length, 1);
    assert.equal(plan[0].index, 0);
    assert.equal(plan[0].offset, 0);
    assert.equal(plan[0].size, bytes.byteLength);
    assert.equal(plan[0].sha256, await digest.digestBytes(bytes));
});
