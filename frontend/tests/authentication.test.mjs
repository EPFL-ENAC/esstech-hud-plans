import assert from 'node:assert/strict';
import { test } from 'node:test';
import { effectScope, isReadonly } from 'vue';
import { importTypeScript } from './helpers/typescript.mjs';

function token(ownerId, expiresAt = 4_000_000_000) {
    return `test.${Buffer.from(JSON.stringify({ sub: ownerId, exp: expiresAt })).toString('base64url')}.test`;
}

async function setup(t, initialToken = token('owner')) {
    const originals = new Map(
        ['window', 'localStorage'].map((key) => [
            key,
            Object.getOwnPropertyDescriptor(globalThis, key),
        ]),
    );
    const browserWindow = new EventTarget();
    const values = new Map();
    const storage = {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
    };
    if (initialToken !== null) storage.setItem('access_token', initialToken);
    Object.defineProperty(globalThis, 'window', { configurable: true, value: browserWindow });
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });

    const scopes = [];
    t.after(() => {
        for (const scope of scopes) scope.stop();
        for (const [key, descriptor] of originals) {
            if (descriptor) Object.defineProperty(globalThis, key, descriptor);
            else delete globalThis[key];
        }
    });

    const session = await importTypeScript(t, 'src/lib/auth.ts', {
        'boot/api': {
            baseUrl: 'https://example.test/api',
            keycloakClientId: 'test',
            keycloakEndpoint: 'https://example.test',
            keycloakRealm: 'test',
            keycloakRedirectUri: 'https://example.test/callback',
        },
    });
    const { useAuthentication } = await importTypeScript(
        t,
        'src/composables/useAuthentication.ts',
        { vue: import.meta.resolve('vue'), 'src/lib/auth': session },
    );

    return {
        session,
        storage,
        observe(options) {
            const scope = effectScope();
            scopes.push(scope);
            return { auth: scope.run(() => useAuthentication(options)), scope };
        },
        focus() {
            browserWindow.dispatchEvent(new Event('focus'));
        },
        storageEvent(key = 'access_token') {
            browserWindow.dispatchEvent(
                Object.assign(new Event('storage'), { key, storageArea: storage }),
            );
        },
    };
}

test('initial authentication refs are readonly and do not invoke onChange', async (t) => {
    const { observe } = await setup(t);
    const changes = [];
    const { auth } = observe({ onChange: (...args) => changes.push(args) });
    assert.equal(auth.ownerId.value, 'owner');
    assert.equal(auth.isAuthenticated.value, true);
    assert.equal(isReadonly(auth.ownerId), true);
    assert.equal(isReadonly(auth.isAuthenticated), true);
    assert.deepEqual(changes, []);
});

test('missing and malformed tokens initialize an unauthenticated session', async (t) => {
    const { observe, storage } = await setup(t, null);
    const { auth } = observe();
    assert.equal(auth.ownerId.value, null);
    assert.equal(auth.isAuthenticated.value, false);
    storage.setItem('access_token', 'malformed');
    assert.equal(auth.refreshAuthentication(), false);
    assert.equal(auth.ownerId.value, null);
});

test('manual refresh publishes both fields before synchronous and reentrant notification', async (t) => {
    const { observe, storage } = await setup(t, null);
    const changes = [];
    const { auth } = observe({
        onChange(current, previous) {
            assert.equal(auth.ownerId.value, current.ownerId);
            assert.equal(auth.isAuthenticated.value, current.isAuthenticated);
            assert.equal(auth.refreshAuthentication(), current.isAuthenticated);
            changes.push({ current, previous });
        },
    });

    storage.setItem('access_token', token('new-owner'));
    assert.equal(auth.ownerId.value, null);
    assert.equal(auth.refreshAuthentication(), true);
    assert.deepEqual(changes, [
        {
            previous: { ownerId: null, isAuthenticated: false },
            current: { ownerId: 'new-owner', isAuthenticated: true },
        },
    ]);
});

test('token setters and logout notify only when the observed session changes', async (t) => {
    const { observe, session, focus } = await setup(t);
    const changes = [];
    const { auth } = observe({ onChange: (...args) => changes.push(args) });
    session.setAccessToken(token('owner', 4_100_000_000));
    focus();
    auth.refreshAuthentication();
    assert.equal(changes.length, 0);

    session.setAccessToken(token('another-owner'));
    assert.equal(auth.ownerId.value, 'another-owner');
    assert.equal(changes.length, 1);
    session.logout();
    assert.equal(auth.ownerId.value, null);
    assert.equal(auth.isAuthenticated.value, false);
    assert.equal(changes.length, 2);
});

test('cross-tab token replacement and storage clearing update the session synchronously', async (t) => {
    const { observe, storage, storageEvent } = await setup(t);
    const { auth } = observe();
    storage.setItem('access_token', token('another-owner'));
    storageEvent('unrelated');
    assert.equal(auth.ownerId.value, 'owner');
    storageEvent();
    assert.equal(auth.ownerId.value, 'another-owner');
    storage.removeItem('access_token');
    storageEvent(null);
    assert.equal(auth.ownerId.value, null);
    assert.equal(auth.isAuthenticated.value, false);
});

test('focus detects token expiry without a timer', async (t) => {
    const { observe, focus } = await setup(t);
    const changes = [];
    const { auth } = observe({ onChange: (...args) => changes.push(args) });
    t.mock.method(Date, 'now', () => 4_000_000_000_000);
    focus();
    assert.equal(auth.ownerId.value, 'owner');
    assert.equal(auth.isAuthenticated.value, false);
    assert.equal(changes.length, 1);
    focus();
    assert.equal(changes.length, 1);
});

test('disposing one consumer removes its listeners without stopping another consumer', async (t) => {
    const { observe, session, storage, storageEvent, focus } = await setup(t);
    const changes = [];
    const first = observe({ onChange: (...args) => changes.push(args) });
    const second = observe();
    first.scope.stop();
    session.setAccessToken(token('another-owner'));
    assert.equal(first.auth.ownerId.value, 'owner');
    assert.equal(second.auth.ownerId.value, 'another-owner');
    storage.removeItem('access_token');
    storageEvent(null);
    focus();
    assert.equal(first.auth.ownerId.value, 'owner');
    assert.equal(second.auth.ownerId.value, null);
    assert.deepEqual(changes, []);
});
