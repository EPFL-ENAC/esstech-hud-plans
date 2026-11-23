import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as vue from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

async function fixture(t, buildingId) {
    const uploads = [];
    const navigations = [];
    let unmount;
    let subject = 'owner';
    let navigationFails = false;
    const { useUploadForReconstruction } = await importTypeScript(
        t,
        'src/composables/useUploadForReconstruction.ts',
        {
            vue: {
                computed: vue.computed,
                ref: vue.ref,
                readonly: vue.readonly,
                onBeforeUnmount: (callback) => {
                    unmount = callback;
                },
            },
            'vue-router': {
                useRoute: () => ({ query: { buildingId } }),
                useRouter: () => ({
                    replace(to) {
                        navigations.push(to);
                        return Promise.resolve(navigationFails ? { type: 'aborted' } : undefined);
                    },
                }),
            },
            'vue-i18n': { useI18n: () => ({ t: (key) => key }) },
            'src/lib/api': { ApiError },
            'src/lib/auth': { getAuthSubject: () => subject },
            'src/mutations/uploads': {
                useScheduleVideoUploadMutation: () => ({
                    mutateAsync(variables) {
                        const gate = deferred();
                        uploads.push({ ...variables, gate });
                        return gate.promise;
                    },
                }),
            },
        },
    );
    const uploader = useUploadForReconstruction();
    return {
        uploader,
        uploads,
        navigations,
        unmount: () => unmount(),
        setSubject: (value) => {
            subject = value;
        },
        failNavigation: (value) => {
            navigationFails = value;
        },
    };
}

const file = { name: 'video.mp4', size: 100 };
const scheduled = { localUploadId: 'local-id', taskId: 'task-id' };

for (const buildingId of [undefined, 'existing-building']) {
    test(`opens the form after scheduling with building ${buildingId}`, async (t) => {
        const f = await fixture(t, buildingId);
        const handoff = f.uploader.startUpload(file);

        assert.equal(f.uploader.busy.value, true);
        await f.uploader.startUpload(file);
        assert.equal(f.uploads.length, 1);
        assert.deepEqual(f.navigations, []);

        f.uploads[0].gate.resolve(scheduled);
        await handoff;

        assert.equal(f.uploader.busy.value, false);
        assert.equal(f.uploader.localUploadId.value, 'local-id');
        assert.deepEqual(f.navigations, [
            {
                name: 'reconstruction-from-local-upload',
                params: { localUploadId: 'local-id' },
                query: { buildingId },
            },
        ]);
    });
}

test('retries the failed step', async (t) => {
    const f = await fixture(t, 'existing-building');
    const firstAttempt = f.uploader.startUpload(file);
    f.uploads[0].gate.reject(new Error('Storage unavailable'));
    await firstAttempt;

    assert.equal(f.uploader.errorMessage.value, 'reconstructions.fromUpload.scheduleFailed');
    assert.equal(f.uploader.localUploadId.value, null);
    assert.deepEqual(f.navigations, []);

    f.failNavigation(true);
    const retry = f.uploader.retry();
    assert.equal(f.uploads[1].file, file);
    f.uploads[1].gate.resolve(scheduled);
    await retry;

    assert.equal(f.uploader.errorMessage.value, 'reconstructions.fromUpload.navigationFailed');
    f.failNavigation(false);
    await f.uploader.retry();

    assert.equal(f.uploads.length, 2);
    assert.equal(f.navigations.length, 2);
    assert.deepEqual(f.navigations[1], f.navigations[0]);
    assert.equal(f.uploader.errorMessage.value, '');
});

test('empty files and changed accounts cannot schedule an upload', async (t) => {
    const f = await fixture(t);
    await f.uploader.startUpload({ name: 'empty.mp4', size: 0 });
    assert.equal(f.uploader.errorMessage.value, 'uploads.new.emptyFile');

    f.setSubject('other');
    await f.uploader.startUpload(file);
    assert.equal(f.uploader.errorMessage.value, 'uploads.new.authFailed');
    assert.equal(f.uploads.length, 0);
});

for (const leavePage of [false, true]) {
    test(`suppresses a late handoff after ${leavePage ? 'unmount' : 'account change'}`, async (t) => {
        const f = await fixture(t);
        const handoff = f.uploader.startUpload(file);
        if (leavePage) f.unmount();
        else f.setSubject('other');

        f.uploads[0].gate.resolve(scheduled);
        await handoff;

        assert.deepEqual(f.navigations, []);
        assert.equal(f.uploader.localUploadId.value, null);
    });
}
