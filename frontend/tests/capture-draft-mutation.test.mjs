import assert from 'node:assert/strict';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { createApp, effectScope } from 'vue';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { PiniaColada } from '@pinia/colada';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t) {
    let subject = 'owner';
    const commit = deferred();
    const transfer = deferred();
    const onCreate = t.mock.fn();
    const upload = t.mock.fn(() => transfer.promise);
    const attach = t.mock.fn(async () => {});
    const { useCreateCaptureDraftMutation } = await importTypeScript(
        t,
        'src/mutations/captureDrafts.ts',
        {
            vue: import.meta.resolve('vue'),
            '@pinia/colada': import.meta.resolve('@pinia/colada'),
            'vue-i18n': { useI18n: () => ({ t: (key) => key }) },
            'src/lib/auth': { getAuthSubject: () => subject },
            'src/lib/captureDraftService': {
                CaptureDraftService: class {
                    create = () => commit.promise;
                    attachUpload = attach;
                },
            },
            'src/queries/captureDrafts': {
                captureDraftUploadKey: (ownerId, id) => ['capture-drafts', ownerId, id, 'upload'],
            },
            './uploads': { useUploadVideoMutation: () => ({ mutateAsync: upload }) },
        },
    );
    const app = createApp({});
    const pinia = createPinia();
    app.use(pinia);
    app.use(PiniaColada);
    const scope = effectScope();
    t.after(() => {
        scope.stop();
        disposePinia(pinia);
        setActivePinia(undefined);
    });
    const mutation = app.runWithContext(() =>
        scope.run(() => useCreateCaptureDraftMutation({ onCreate })),
    );
    return {
        mutation,
        commit,
        transfer,
        onCreate,
        upload,
        attach,
        dispose: () => scope.stop(),
        changeAccount: () => (subject = 'other-owner'),
    };
}

const existingUpload = { source: { uploadId: 'upload-id' }, buildingId: null };

test('onCreate fires once after the local commit and before upload completion', async (t) => {
    const f = await fixture(t);
    const video = new File(['video'], 'capture.mp4');
    const creation = f.mutation.mutateAsync({ source: { video }, buildingId: null });
    await nextTurn();
    assert.equal(f.onCreate.mock.callCount(), 0);
    assert.equal(f.upload.mock.callCount(), 0);

    f.commit.resolve('draft-id');
    assert.equal(await creation, 'draft-id');
    assert.equal(f.upload.mock.callCount(), 1);
    assert.deepEqual(
        f.onCreate.mock.calls.map(({ arguments: args }) => args),
        [['draft-id']],
    );
    assert.equal(f.attach.mock.callCount(), 0);

    f.transfer.resolve({ uploadId: 'upload-id' });
    await nextTurn();
    assert.equal(f.attach.mock.callCount(), 1);
    assert.equal(f.onCreate.mock.callCount(), 1);
});

test('a failed local commit never calls onCreate', async (t) => {
    const f = await fixture(t);
    const creation = f.mutation.mutateAsync(existingUpload);
    const rejected = assert.rejects(creation, /Commit failed/);
    await nextTurn();
    f.commit.reject(new Error('Commit failed'));
    await rejected;
    assert.equal(f.onCreate.mock.callCount(), 0);
});

for (const invalidate of ['dispose', 'changeAccount']) {
    test(`${invalidate} during creation suppresses onCreate`, async (t) => {
        const f = await fixture(t);
        const creation = f.mutation.mutateAsync(existingUpload);
        await nextTurn();
        f[invalidate]();
        f.commit.resolve('draft-id');
        assert.equal(await creation, 'draft-id');
        assert.equal(f.onCreate.mock.callCount(), 0);
    });
}
