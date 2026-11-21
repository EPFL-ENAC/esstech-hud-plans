import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { effectScope, ref } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const { useDebouncedAutosave } = await importTypeScript(
        t,
        'src/composables/useDebouncedAutosave.ts',
        { vue: import.meta.resolve('vue') },
    );
    const scope = effectScope();
    t.after(() => scope.stop());
    const form = ref();
    const writes = [];
    const autosave = scope.run(() =>
        useDebouncedAutosave(
            () => form.value,
            (value) => {
                const gate = deferred();
                writes.push({ fps: value.settings.fps, gate });
                return gate.promise;
            },
            300,
        ),
    );

    form.value = { settings: { fps: 2 } };
    return {
        autosave,
        writes,
        edit(fps) {
            form.value.settings.fps = fps;
        },
        async advance(milliseconds) {
            t.mock.timers.tick(milliseconds);
            await nextTurn();
        },
        dispose: () => scope.stop(),
    };
}

test('loading does not write and rapid nested edits save once after a pause', async (t) => {
    const { autosave, writes, edit, advance } = await fixture(t);
    await advance(300);
    assert.equal(writes.length, 0);
    assert.equal(autosave.status.value, 'saved');

    edit(3);
    assert.equal(autosave.status.value, 'saving');
    await advance(200);
    edit(4);
    await advance(299);
    assert.equal(writes.length, 0);
    await advance(1);
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [4],
    );

    writes[0].gate.resolve();
    await autosave.flush();
    assert.equal(autosave.status.value, 'saved');
});

test('edits during a slow write coalesce into one follow-up write', async (t) => {
    const { autosave, writes, edit, advance } = await fixture(t);
    edit(3);
    await advance(300);
    edit(4);
    edit(5);
    await advance(300);
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [3],
    );

    writes[0].gate.resolve();
    await nextTurn();
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [3, 5],
    );
    assert.equal(autosave.status.value, 'saving');

    writes[1].gate.resolve();
    await autosave.flush();
    assert.equal(autosave.status.value, 'saved');
});

test('flush skips the timer and waits for all writes in order', async (t) => {
    const { autosave, writes, edit } = await fixture(t);
    edit(3);
    let flushed = false;
    const flush = autosave.flush().then(() => {
        flushed = true;
    });
    await nextTurn();
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [3],
    );
    assert.equal(flushed, false);

    edit(4);
    writes[0].gate.resolve();
    await nextTurn();
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [3, 4],
    );
    assert.equal(flushed, false);

    writes[1].gate.resolve();
    await flush;
    assert.equal(autosave.status.value, 'saved');
});

test('retry writes immediately after a failure', async (t) => {
    const { autosave, writes, edit, advance } = await fixture(t);
    edit(3);
    await advance(300);
    writes[0].gate.reject(new Error('Write failed'));
    await autosave.flush();
    assert.equal(autosave.status.value, 'error');
    assert.equal(writes.length, 1);

    const retry = autosave.retry();
    await nextTurn();
    assert.deepEqual(
        writes.map(({ fps }) => fps),
        [3, 3],
    );
    writes[1].gate.resolve();
    await retry;
    assert.equal(autosave.status.value, 'saved');
});

test('disposing cancels a queued write', async (t) => {
    const { writes, edit, advance, dispose } = await fixture(t);
    edit(3);
    dispose();
    await advance(300);
    assert.equal(writes.length, 0);
});
