import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setImmediate as nextTurn } from 'node:timers/promises';
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
    const notifications = [];
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
            'vue-i18n': {
                useI18n: () => ({
                    t: (key, params) => (params ? `${key}:${params.filename}` : key),
                }),
            },
            quasar: {
                useQuasar: () => ({ notify: (notification) => notifications.push(notification) }),
            },
            'src/lib/api': { ApiError },
            'src/lib/auth': { getAuthSubject: () => subject },
            'src/mutations/uploads': {
                useUploadVideoMutation: () => ({
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
        notifications,
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

for (const buildingId of [undefined, 'existing-building']) {
    test(`navigates on availability once with building context ${buildingId}, while completion only notifies`, async (t) => {
        const f = await fixture(t, buildingId);
        f.uploader.startUpload(file);
        assert.equal(f.uploader.busy.value, true);
        f.uploader.startUpload(file);
        assert.equal(f.uploads.length, 1);
        f.uploads[0].onUploadAvailable('pending-id');
        await nextTurn();
        assert.equal(f.uploader.busy.value, false);
        assert.equal(f.uploader.uploadId.value, 'pending-id');
        assert.deepEqual(f.navigations, [
            {
                name: 'reconstruction-from-upload',
                params: { uploadId: 'pending-id' },
                query: { buildingId },
            },
        ]);
        assert.deepEqual(f.notifications, []);
        f.uploads[0].onUploadAvailable('pending-id');
        f.uploads[0].onUploadAvailable('another-id');
        assert.equal(f.navigations.length, 1);
        f.unmount();
        f.uploads[0].gate.resolve({ uploadId: 'pending-id' });
        await nextTurn();
        assert.equal(f.navigations.length, 1);
        assert.equal(f.notifications[0].type, 'positive');
    });
}

test('creation errors retry the retained file; navigation errors retry only navigation', async (t) => {
    const f = await fixture(t, 'existing-building');
    f.uploader.startUpload(file);
    f.uploads[0].gate.reject(new ApiError('Invalid', 400));
    await nextTurn();
    assert.equal(f.uploader.errorMessage.value, 'uploads.new.invalidVideo');
    await f.uploader.retry();
    assert.equal(f.uploads.length, 2);
    assert.equal(f.uploads[1].file, file);
    f.failNavigation(true);
    f.uploads[1].onUploadAvailable('created');
    await nextTurn();
    assert.equal(f.uploader.errorMessage.value, 'reconstructions.fromUpload.navigationFailed');
    f.failNavigation(false);
    await f.uploader.retry();
    assert.equal(f.uploads.length, 2);
    assert.equal(f.navigations.length, 2);
    for (const navigation of f.navigations) {
        assert.deepEqual(navigation, {
            name: 'reconstruction-from-upload',
            params: { uploadId: 'created' },
            query: { buildingId: 'existing-building' },
        });
    }
    assert.equal(f.uploader.errorMessage.value, '');
    f.uploads[1].gate.resolve({ uploadId: 'created' });
    await nextTurn();
});

test('empty files and changed accounts never start a transfer', async (t) => {
    const f = await fixture(t);
    f.uploader.startUpload({ name: 'empty.mp4', size: 0 });
    assert.equal(f.uploader.errorMessage.value, 'uploads.new.emptyFile');
    f.setSubject('other');
    f.uploader.startUpload(file);
    assert.equal(f.uploader.errorMessage.value, 'uploads.new.authFailed');
    assert.equal(f.uploads.length, 0);
});

test('leaving before creation finishes prevents late automatic navigation', async (t) => {
    const f = await fixture(t);
    f.uploader.startUpload(file);
    f.unmount();
    f.uploads[0].onUploadAvailable('late-id');
    f.uploads[0].gate.resolve({ uploadId: 'late-id' });
    await nextTurn();
    assert.equal(f.navigations.length, 0);
    assert.equal(f.notifications[0].type, 'positive');
});

for (const fail of [false, true]) {
    test(`account changes suppress late navigation and notifications (failure: ${fail})`, async (t) => {
        const f = await fixture(t);
        f.uploader.startUpload(file);
        f.setSubject(null);
        f.uploads[0].onUploadAvailable('private-id');
        if (fail) f.uploads[0].gate.reject(new Error('Interrupted'));
        else f.uploads[0].gate.resolve({ uploadId: 'private-id' });
        await nextTurn();
        assert.deepEqual(f.navigations, []);
        assert.deepEqual(f.notifications, []);
    });
}

test('transfer errors after navigation notify without changing the destination', async (t) => {
    const f = await fixture(t);
    f.uploader.startUpload(file);
    f.uploads[0].onUploadAvailable('pending');
    f.unmount();
    f.uploads[0].gate.reject(new Error('Interrupted'));
    await nextTurn();
    assert.equal(f.navigations.length, 1);
    assert.equal(f.notifications[0].type, 'negative');
    assert.match(f.notifications[0].message, /video.mp4/);
});
