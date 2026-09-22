import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Use the existing TypeScript compiler so the tests also run on Node 20.
const { outputText } = ts.transpileModule(
    readFileSync(new URL('../src/lib/cameras.ts', import.meta.url), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
);
const { detectCameraSide } = await import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
);

test('uses only a single explicit facing mode', () => {
    for (const [facingMode, expected] of [
        [['user'], 'front'],
        [['environment'], 'rear'],
        [['user', 'environment'], null],
        [['user', 'user'], null],
        [['left'], null],
        [[], null],
        [undefined, null],
    ]) {
        assert.equal(detectCameraSide({ getCapabilities: () => ({ facingMode }) }), expected);
    }
});

test('missing or failed capabilities stay unknown regardless of the label', () => {
    assert.equal(detectCameraSide({ label: 'Front Camera' }), null);
    assert.equal(
        detectCameraSide({
            label: 'Rear Camera',
            getCapabilities() {
                throw new Error('unsupported');
            },
        }),
        null,
    );
});
