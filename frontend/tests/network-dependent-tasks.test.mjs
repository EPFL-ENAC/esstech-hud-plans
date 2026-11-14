import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { effectScope, isProxy, isReadonly, watchEffect } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';

async function flush() {
    await new Promise((resolve) => setImmediate(resolve));
}

function untilAborted(signal) {
    return new Promise((resolve, reject) => {
        if (signal.aborted) reject(signal.reason);
        else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
}

async function setup(t, { online = true } = {}) {
    const originals = new Map(
        ['window', 'navigator'].map((key) => [
            key,
            Object.getOwnPropertyDescriptor(globalThis, key),
        ]),
    );
    const browserWindow = new EventTarget();
    const browserNavigator = { onLine: online };
    const authListeners = new Set();
    let subject = 'owner';
    let authenticated = true;
    let queue;
    let pinia;

    Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: browserWindow,
    });
    Object.defineProperty(globalThis, 'navigator', {
        configurable: true,
        value: browserNavigator,
    });

    t.after(async () => {
        queue?.$dispose();
        await queue?.clear();
        if (pinia) disposePinia(pinia);
        setActivePinia(undefined);
        for (const [key, descriptor] of originals) {
            if (descriptor) Object.defineProperty(globalThis, key, descriptor);
            else delete globalThis[key];
        }
    });

    const { NetworkDependentTask } = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const connection = await importTypeScript(t, 'src/composables/useOnlineConnection.ts', {
        vue: import.meta.resolve('vue'),
    });
    const authentication = await importTypeScript(t, 'src/composables/useAuthentication.ts', {
        vue: import.meta.resolve('vue'),
        'src/lib/auth': {
            getAuthSubject: () => subject,
            isAuthenticated: () => authenticated,
            subscribeAuthChanges(listener) {
                authListeners.add(listener);
                return () => authListeners.delete(listener);
            },
        },
    });
    const { useNetworkDependentTasks } = await importTypeScript(
        t,
        'src/stores/networkDependentTasks.ts',
        {
            vue: import.meta.resolve('vue'),
            pinia: import.meta.resolve('pinia'),
            'src/composables/useOnlineConnection': connection,
            'src/composables/useAuthentication': authentication,
        },
    );

    class TestTask extends NetworkDependentTask {
        constructor({
            ownerId = 'owner',
            operation = () => Promise.resolve(),
            action = 'failed',
        } = {}) {
            super({ ownerId, label: 'Test task' });
            this.operation = operation;
            this.action = action;
            this.calls = 0;
            this.interruptions = [];
            this.cleanup = null;
            this.signal = null;
        }

        async resume(signal) {
            this.calls += 1;
            this.signal = signal;
            await this.operation(signal, this);
        }

        failureAction() {
            return this.action;
        }

        async onInterrupt(reason) {
            this.interruptions.push(reason);
            await this.cleanup?.(reason);
        }

        report(completed, total, message = null) {
            this.mutableState.progress = { completed, total };
            this.mutableState.message = message;
        }
    }

    pinia = createPinia();
    setActivePinia(pinia);
    queue = useNetworkDependentTasks();

    return {
        queue,
        TestTask,
        connection,
        browserWindow,
        authListeners,
        connect(value) {
            browserNavigator.onLine = value;
            browserWindow.dispatchEvent(new Event(value ? 'online' : 'offline'));
        },
        setAuth(nextSubject, nextAuthenticated, notify = true) {
            subject = nextSubject;
            authenticated = nextAuthenticated;
            if (notify) for (const listener of authListeners) listener();
        },
    };
}

test('connectivity callbacks fire only on transitions and stop with their scope', async (t) => {
    const { connection, connect, browserWindow } = await setup(t);
    const calls = [];
    const scope = effectScope();
    const { isOnline } = scope.run(() =>
        connection.useOnlineConnection({
            onOnline: () => calls.push('online'),
            onOffline: () => calls.push('offline'),
        }),
    );

    assert.equal(isReadonly(isOnline), true);
    connect(false);
    connect(false);
    connect(true);
    browserWindow.dispatchEvent(new Event('online'));
    assert.deepEqual(calls, ['offline', 'online']);
    scope.stop();
    connect(false);
    assert.equal(isOnline.value, true);
    assert.deepEqual(calls, ['offline', 'online']);
});

test('offline submissions start concurrently on reconnect', async (t) => {
    const { queue, TestTask, connect } = await setup(t, { online: false });
    const first = new TestTask({ operation: untilAborted });
    const second = new TestTask({ operation: untilAborted });
    queue.submit(first);
    queue.submit(second);
    await flush();
    assert.equal(first.calls, 0);
    assert.equal(second.calls, 0);
    assert.equal(queue.pendingCount, 2);

    connect(true);
    await flush();
    assert.equal(first.state.status, 'running');
    assert.equal(second.state.status, 'running');
    await queue.clear();
});

test('raw task instances expose reactive readonly UI state', async (t) => {
    const { queue, TestTask } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    let rendered = '';
    const stop = watchEffect(() => {
        rendered = queue.tasks
            .map(
                (entry) =>
                    `${entry.state.status}:${entry.state.progress?.completed ?? 0}:${entry.state.message}`,
            )
            .join('|');
    });
    t.after(stop);
    queue.submit(task);
    await flush();
    assert.equal(queue.get(task.id), task);
    assert.equal(isProxy(task), false);
    assert.equal(isReadonly(task.state), true);
    assert.equal(rendered, 'running:0:null');

    task.report(3, 10, 'Uploading');
    await flush();
    assert.equal(rendered, 'running:3:Uploading');
    await queue.cancel(task.id);
    await flush();
    assert.equal(rendered, '');
    assert.equal(task.state.status, 'cancelled');
});

test('transient failures wait for reconnect or manual retry without blocking other work', async (t) => {
    const { queue, TestTask, connect, browserWindow } = await setup(t);
    const task = new TestTask({
        action: 'retry',
        operation: async (_signal, current) => {
            if (current.calls < 3) throw new Error('Connection interrupted');
        },
    });
    queue.submit(task);
    await flush();
    assert.equal(task.state.status, 'waiting');

    const other = new TestTask();
    queue.submit(other);
    browserWindow.dispatchEvent(new Event('online'));
    browserWindow.dispatchEvent(new Event('focus'));
    await flush();
    assert.equal(other.state.status, 'completed');
    assert.equal(task.calls, 1);

    queue.retry(task.id);
    await flush();
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'waiting');
    connect(false);
    connect(true);
    await flush();
    assert.equal(task.calls, 3);
    assert.equal(task.state.status, 'completed');
    assert.equal(queue.pendingCount, 0);
});

test('blocked and permanently failed tasks require manual retry', async (t) => {
    const { queue, TestTask, connect } = await setup(t);
    for (const action of ['blocked', 'failed']) {
        const task = new TestTask({
            action,
            operation: async () => {
                throw new Error('Needs attention');
            },
        });
        queue.submit(task);
        await flush();
        connect(false);
        connect(true);
        await flush();
        assert.equal(task.state.status, action);
        assert.equal(task.calls, 1);
        queue.retry(task.id);
        await flush();
        assert.equal(task.calls, 2);
        await queue.cancel(task.id);
    }
});

test('submission validates identity, account, and lifecycle', async (t) => {
    const { queue, TestTask } = await setup(t);
    const task = new TestTask();
    queue.submit(task);
    assert.throws(() => queue.submit(task), /already enqueued/);
    assert.throws(() => queue.submit(new TestTask({ ownerId: 'other' })), /another account/);
    await flush();
    assert.throws(() => queue.submit(task), /Only queued tasks/);
    queue.retry('missing');
    await queue.cancel('missing');
});

test('cancellation waits for late work without blocking other tasks or accepting late success', async (t) => {
    const { queue, TestTask } = await setup(t);
    const work = deferred();
    const first = new TestTask({ operation: () => work.promise });
    queue.submit(first);
    await flush();
    const cancellation = queue.cancel(first.id);
    const second = new TestTask({ operation: untilAborted });
    queue.submit(second);
    await flush();
    assert.equal(first.signal.aborted, true);
    assert.equal(first.state.status, 'cancelling');
    assert.equal(second.state.status, 'running');
    work.resolve();
    await cancellation;
    assert.equal(first.state.status, 'cancelled');
    assert.equal(queue.get(first.id), undefined);
    assert.equal(second.state.status, 'running');
    await queue.cancel(second.id);
});

test('reconnect waits for pause cleanup and creates a fresh signal', async (t) => {
    const { queue, TestTask, connect } = await setup(t);
    const cleanup = deferred();
    const signals = [];
    const task = new TestTask({
        operation: async (signal, current) => {
            signals.push(signal);
            if (current.calls === 1) await untilAborted(signal);
        },
    });
    task.cleanup = (reason) => (reason === 'pause' ? cleanup.promise : Promise.resolve());
    queue.submit(task);
    await flush();
    connect(false);
    await flush();
    connect(true);
    await flush();
    assert.equal(task.state.status, 'pausing');
    assert.equal(task.calls, 1);
    cleanup.resolve();
    await flush();
    assert.equal(task.calls, 2);
    assert.notEqual(signals[0], signals[1]);
    assert.equal(signals[0].aborted, true);
    assert.equal(signals[1].aborted, false);
    assert.equal(task.state.status, 'completed');
    assert.equal(queue.pendingCount, 0);
});

test('cancellation supersedes pause, even during reconnect', async (t) => {
    const { queue, TestTask, connect } = await setup(t);
    const cleanup = deferred();
    const task = new TestTask({ operation: untilAborted });
    task.cleanup = (reason) => (reason === 'pause' ? cleanup.promise : Promise.resolve());
    queue.submit(task);
    await flush();
    connect(false);
    await flush();
    const cancellation = queue.cancel(task.id);
    connect(true);
    cleanup.resolve();
    await cancellation;
    await flush();
    assert.deepEqual(task.interruptions, ['pause', 'cancel']);
    assert.equal(task.state.status, 'cancelled');
    assert.equal(task.calls, 1);
    assert.equal(queue.pendingCount, 0);
});

test('repeated calls share an attempt and cannot revive a cancelled task', async (t) => {
    const { queue, TestTask, browserWindow } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    queue.submit(task);
    queue.retry(task.id);
    queue.retry(task.id);
    browserWindow.dispatchEvent(new Event('focus'));
    await flush();
    assert.equal(task.calls, 1);
    const attempt = task.retryOrResume();
    assert.equal(task.retryOrResume(), attempt);
    const cancellation = task.cancel();
    assert.equal(task.cancel(), cancellation);
    await cancellation;
    await attempt;
    await queue.cancel(task.id);
    task.requestRetry();
    await task.retryOrResume();
    assert.equal(task.calls, 1);
    assert.equal(task.state.status, 'cancelled');
});

test('account changes synchronously hide and cancel previous tasks', async (t) => {
    const { queue, TestTask, setAuth } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    queue.submit(task);
    await flush();
    setAuth('other', true);
    assert.equal(queue.pendingCount, 0);
    assert.equal(task.signal.aborted, true);
    assert.throws(() => queue.submit(new TestTask()), /another account/);
    const next = new TestTask({ ownerId: 'other' });
    queue.submit(next);
    await flush();
    assert.equal(task.state.status, 'cancelled');
    assert.equal(next.state.status, 'completed');
});

test('focus detects expired auth and renewed auth resumes queued work', async (t) => {
    const { queue, TestTask, setAuth, browserWindow } = await setup(t);
    const task = new TestTask({
        operation: async (signal, current) => {
            if (current.calls === 1) await untilAborted(signal);
        },
    });
    queue.submit(task);
    await flush();
    setAuth('owner', false, false);
    browserWindow.dispatchEvent(new Event('focus'));
    await flush();
    assert.equal(queue.authenticationRequired, true);
    assert.equal(task.state.status, 'queued');
    assert.throws(() => queue.submit(new TestTask()), /Sign in/);
    setAuth('owner', true);
    await flush();
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'completed');
});

test('disposal cancels tasks, removes listeners, and prevents pending execution', async (t) => {
    const { queue, TestTask, connect, authListeners } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    queue.submit(task);
    await flush();
    const pending = new TestTask();
    queue.submit(pending);
    queue.$dispose();
    assert.equal(authListeners.size, 0);
    assert.equal(queue.pendingCount, 0);
    connect(false);
    assert.equal(queue.isOnline, true);
    await flush();
    assert.equal(task.state.status, 'cancelled');
    assert.equal(pending.calls, 0);
    connect(true);
    await flush();
    assert.equal(task.calls, 1);
});

test('interruption hook errors do not reject cancellation or revive the task', async (t) => {
    const { queue, TestTask } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    task.cleanup = async () => {
        throw new Error('Cleanup failed');
    };
    const warnings = [];
    t.mock.method(console, 'warn', (...args) => warnings.push(args));
    queue.submit(task);
    await flush();
    await queue.cancel(task.id);
    assert.equal(task.state.status, 'cancelled');
    assert.equal(warnings.length, 1);
});

test('auth subscriptions observe token changes, cross-tab changes and clearing local data', async (t) => {
    const { browserWindow } = await setup(t);
    const originals = new Map(
        ['localStorage', 'sessionStorage', 'indexedDB'].map((key) => [
            key,
            Object.getOwnPropertyDescriptor(globalThis, key),
        ]),
    );
    const values = new Map();
    const storage = {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
        clear: () => values.clear(),
    };
    for (const [key, value] of Object.entries({
        localStorage: storage,
        sessionStorage: { clear() {} },
        indexedDB: { databases: async () => [] },
    })) {
        Object.defineProperty(globalThis, key, { configurable: true, value });
    }
    t.after(() => {
        for (const [key, descriptor] of originals) {
            if (descriptor) Object.defineProperty(globalThis, key, descriptor);
            else delete globalThis[key];
        }
    });

    const auth = await importTypeScript(t, 'src/lib/auth.ts', {
        'boot/api': {
            baseUrl: 'https://example.test/api',
            keycloakClientId: 'test',
            keycloakEndpoint: 'https://example.test',
            keycloakRealm: 'test',
            keycloakRedirectUri: 'https://example.test/callback',
        },
    });
    let calls = 0;
    const unsubscribe = auth.subscribeAuthChanges(() => {
        calls += 1;
    });
    auth.setAccessToken('token');
    auth.clearAccessToken();
    assert.equal(calls, 2);
    for (const key of ['unrelated', 'access_token', null]) {
        browserWindow.dispatchEvent(
            Object.assign(new Event('storage'), { storageArea: storage, key }),
        );
    }
    assert.equal(calls, 4);
    await auth.clearLocalData();
    assert.equal(calls, 5);
    unsubscribe();
    auth.setAccessToken('another-token');
    assert.equal(calls, 5);
});
