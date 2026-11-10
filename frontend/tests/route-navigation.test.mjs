import assert from 'node:assert/strict';
import { test } from 'node:test';
import { effectScope, onScopeDispose, readonly, ref } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function fixture(t, router) {
    const { useRouteNavigation } = await importTypeScript(
        t,
        'src/composables/useRouteNavigation.ts',
        { vue: { onScopeDispose, readonly, ref }, 'vue-router': { useRouter: () => router } },
    );
    const scope = effectScope();
    t.after(() => scope.stop());
    return { navigation: scope.run(useRouteNavigation), dispose: () => scope.stop() };
}

test('push and replace share pending state and forward the original target', async (t) => {
    const gate = deferred();
    const calls = [];
    const { navigation } = await fixture(t, {
        push(to) {
            calls.push(['push', to]);
            return gate.promise;
        },
        async replace(to) {
            calls.push(['replace', to]);
        },
    });
    const target = { name: 'capture-draft', params: { draftId: 'id' }, query: { buildingId: 'b' } };

    const pending = navigation.push(target);
    assert.equal(navigation.navigating.value, true);
    assert.equal(navigation.navigationFailed.value, false);
    await navigation.replace('/uploads');
    assert.deepEqual(calls, [['push', target]]);
    assert.equal(navigation.navigating.value, true);

    gate.resolve();
    await pending;
    assert.equal(navigation.navigating.value, false);
    await navigation.replace('/uploads');
    assert.deepEqual(calls, [
        ['push', target],
        ['replace', '/uploads'],
    ]);
    assert.equal(navigation.navigating.value, false);
});

test('resolved failures persist until cleared or a retry succeeds', async (t) => {
    let result = new Error('Navigation aborted');
    const { navigation } = await fixture(t, { replace: async () => result });

    await navigation.replace('/uploads');
    assert.equal(navigation.navigationFailed.value, true);
    assert.equal(navigation.navigating.value, false);
    navigation.clearNavigationFailure();
    assert.equal(navigation.navigationFailed.value, false);
    await navigation.replace('/uploads');
    assert.equal(navigation.navigationFailed.value, true);

    result = undefined;
    const retry = navigation.replace('/uploads');
    assert.equal(navigation.navigationFailed.value, true);
    await retry;
    assert.equal(navigation.navigationFailed.value, false);
});

test('router exceptions and rejections become navigation failures', async (t) => {
    const { navigation } = await fixture(t, {
        push() {
            throw new Error('Invalid route');
        },
        async replace() {
            throw new Error('Guard failed');
        },
    });

    await navigation.push('/unknown');
    assert.equal(navigation.navigationFailed.value, true);
    assert.equal(navigation.navigating.value, false);
    navigation.clearNavigationFailure();
    await navigation.replace('/uploads');
    assert.equal(navigation.navigationFailed.value, true);
    assert.equal(navigation.navigating.value, false);
});

test('disposal suppresses failure updates while allowing a notification action to navigate', async (t) => {
    const gate = deferred();
    const calls = [];
    const { navigation, dispose } = await fixture(t, {
        replace(to) {
            calls.push(to);
            return gate.promise;
        },
    });

    const pending = navigation.replace('/uploads');
    dispose();
    gate.resolve(new Error('Navigation aborted'));
    await pending;
    assert.equal(navigation.navigationFailed.value, false);
    assert.equal(navigation.navigating.value, false);

    await navigation.replace('/uploads');
    assert.deepEqual(calls, ['/uploads', '/uploads']);
    assert.equal(navigation.navigationFailed.value, false);
    assert.equal(navigation.navigating.value, false);
});
