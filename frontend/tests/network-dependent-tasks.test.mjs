import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createPinia, disposePinia, setActivePinia } from 'pinia';
import { effectScope, isProxy, isReadonly, watchEffect } from 'vue';
import { deferred, importTypeScript } from './helpers/typescript.mjs';
import { MemoryTasksDatabase } from './helpers/tasksDatabase.mjs';
import { MemoryLocalUploadsRegistry } from './helpers/localUploadsRegistry.mjs';

function enqueue(queue, task) {
    const submission = queue.submit(task);
    // Legacy lifecycle tests intentionally leave the caller before settlement.
    void submission.catch(() => undefined);
    return submission;
}

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

    const taskModule = await importTypeScript(t, 'src/lib/networkDependentTasks.ts', {
        vue: import.meta.resolve('vue'),
    });
    const { NetworkDependentTask } = taskModule;
    const database = new MemoryTasksDatabase();
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
            'src/lib/networkDependentTasks': taskModule,
            'src/lib/tasksDatabase': {
                TasksDatabase: class {
                    constructor() {
                        return database;
                    }
                },
            },
            'src/lib/localUploadsRegistry': {
                LocalUploadsRegistry: MemoryLocalUploadsRegistry,
            },
            'src/lib/taskRegistry': {
                deserializeTask(snapshot) {
                    const task = new TestTask({
                        id: snapshot.id,
                        createdAt: snapshot.createdAt,
                        ownerId: snapshot.ownerId,
                        action: snapshot.data.action,
                    });
                    task.restoreState(snapshot.state);
                    return task;
                },
            },
        },
    );

    class TestTask extends NetworkDependentTask {
        constructor({
            id,
            createdAt,
            ownerId = 'owner',
            operation = () => Promise.resolve(),
            action = 'failed',
            onCompleted,
        } = {}) {
            super({ id, createdAt, ownerId, label: 'Test task', onCompleted });
            this.operation = operation;
            this.action = action;
            this.calls = 0;
            this.interruptions = [];
            this.cleanup = null;
            this.signal = null;
        }

        serialize() {
            return {
                ...this.serializeBase(),
                type: 'test',
                data: { action: this.action },
            };
        }

        async resume(signal) {
            this.calls += 1;
            this.signal = signal;
            return await this.operation(signal, this);
        }

        failureAction() {
            return this.action;
        }

        async onInterrupt(reason) {
            this.interruptions.push(reason);
            await this.cleanup?.(reason);
        }

        report(completed, total, message = null) {
            this.setProgress({ completed, total });
            this.mutableState.message = message;
        }
    }

    pinia = createPinia();
    setActivePinia(pinia);
    queue = useNetworkDependentTasks();

    return {
        queue,
        database,
        taskModule,
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

test('online submission waits for its attempt and returns its typed result', async (t) => {
    const { queue, TestTask } = await setup(t);
    const work = deferred();
    const task = new TestTask({ operation: () => work.promise });
    const submission = queue.submit(task);
    let settled = false;
    void submission.then(() => {
        settled = true;
    });
    await flush();
    assert.equal(settled, false);
    const result = { id: 'accepted' };
    work.resolve(result);
    assert.deepEqual(await submission, { status: 'completed', taskId: task.id, result });
    assert.equal(queue.get(task.id), undefined);
});

test('void and null are valid completed results', async (t) => {
    const { queue, TestTask } = await setup(t);
    for (const result of [undefined, null]) {
        const task = new TestTask({ operation: async () => result });
        assert.deepEqual(await queue.submit(task), {
            status: 'completed',
            taskId: task.id,
            result,
        });
    }
});

test('completion callbacks run once with the result after concurrent callers and retries', async (t) => {
    const { queue, TestTask } = await setup(t);
    const calls = [];
    const work = deferred();
    const task = new TestTask({
        operation: () => work.promise,
        onCompleted(result) {
            assert.equal(task.state.status, 'completed');
            calls.push(result);
        },
    });
    const submission = queue.submit(task);
    await flush();
    const attempt = task.retryOrResume();
    assert.equal(calls.length, 0);
    const result = { id: 'accepted' };
    work.resolve(result);
    await submission;
    await attempt;
    task.requestRetry();
    await task.retryOrResume();
    assert.deepEqual(calls, [result]);
});

test('completion callbacks wait for a successful background retry', async (t) => {
    const { queue, TestTask, connect } = await setup(t, { online: false });
    const calls = [];
    const task = new TestTask({
        action: 'retry',
        operation: async (_signal, current) => {
            if (current.calls === 1) throw new TypeError('Connection lost');
            return 'accepted';
        },
        onCompleted: (result) => {
            calls.push(result);
        },
    });
    await queue.submit(task);
    assert.deepEqual(calls, []);
    connect(true);
    await flush();
    assert.equal(task.state.status, 'waiting');
    assert.deepEqual(calls, []);
    queue.retry(task.id);
    await flush();
    assert.deepEqual(calls, ['accepted']);
});

test('pause and cancellation suppress completion callbacks for late results', async (t) => {
    const { queue, TestTask } = await setup(t);
    for (const reason of ['pause', 'cancel']) {
        const work = deferred();
        const calls = [];
        const task = new TestTask({
            operation: () => work.promise,
            onCompleted: (result) => {
                calls.push(result);
            },
        });
        const submission = queue.submit(task);
        const settled =
            reason === 'cancel' ? assert.rejects(submission, { name: 'AbortError' }) : submission;
        await flush();
        const interrupted = task[reason]();
        work.resolve('late');
        await interrupted;
        await settled;
        assert.deepEqual(calls, []);
        await queue.cancel(task.id);
    }
});

test('completion callback failures cannot change success or delay submission', async (t) => {
    const { queue, TestTask } = await setup(t);
    const warning = t.mock.method(console, 'warn', () => {});
    const pending = deferred();
    const failure = new Error('Refresh failed');
    for (const onCompleted of [
        () => {
            throw failure;
        },
        () => pending.promise,
    ]) {
        const task = new TestTask({ operation: async () => 'accepted', onCompleted });
        assert.equal((await queue.submit(task)).result, 'accepted');
        assert.equal(task.state.status, 'completed');
        assert.equal(task.failure, null);
    }
    pending.reject(failure);
    await flush();
    assert.equal(warning.mock.callCount(), 2);
});

test('offline submission resolves immediately and later completion cannot resettle it', async (t) => {
    const { queue, TestTask, connect } = await setup(t, { online: false });
    const task = new TestTask({ operation: async () => 'accepted later' });
    const submission = queue.submit(task);
    const outcome = await submission;
    assert.deepEqual(outcome, { status: 'queued', taskId: task.id });
    assert.equal(task.calls, 0);
    connect(true);
    await flush();
    assert.equal(task.state.status, 'completed');
    assert.equal(await submission, outcome);
});

test('retryable initial failure hands off the task and preserves the failure object', async (t) => {
    const { queue, TestTask } = await setup(t);
    const failure = new TypeError('Network failed');
    const task = new TestTask({
        action: 'retry',
        operation: async () => {
            throw failure;
        },
    });
    assert.deepEqual(await queue.submit(task), { status: 'queued', taskId: task.id });
    assert.equal(task.failure, failure);
    assert.equal(queue.get(task.id), task);
});

test('initial permanent and authentication failures reject and remove the task', async (t) => {
    const { queue, TestTask } = await setup(t);
    for (const action of ['failed', 'blocked']) {
        const failure = new Error('Needs attention');
        const task = new TestTask({
            action,
            operation: async () => {
                throw failure;
            },
        });
        await assert.rejects(queue.submit(task), (error) => error === failure);
        assert.equal(task.failure, failure);
        assert.equal(queue.get(task.id), undefined);
    }
});

test('cancelling or switching account during submission rejects with AbortError', async (t) => {
    const { queue, TestTask, setAuth } = await setup(t);
    for (const changeAccount of [false, true]) {
        const task = new TestTask({ operation: untilAborted });
        const rejected = assert.rejects(queue.submit(task), { name: 'AbortError' });
        await flush();
        if (changeAccount) setAuth('other', true);
        else await queue.cancel(task.id);
        await rejected;
        assert.equal(queue.get(task.id), undefined);
    }
});

test('reconnect and manual retry wait for the initial interrupted outcome', async (t) => {
    const { queue, TestTask, connect } = await setup(t);
    const cleanup = deferred();
    const task = new TestTask({
        operation: async (signal, current) => {
            if (current.calls === 1) await untilAborted(signal);
            return 'accepted later';
        },
    });
    task.cleanup = () => cleanup.promise;
    const submission = queue.submit(task);
    await flush();
    connect(false);
    connect(true);
    queue.retry(task.id);
    await flush();
    assert.equal(task.calls, 1);
    cleanup.resolve();
    assert.deepEqual(await submission, { status: 'queued', taskId: task.id });
    await flush();
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'completed');
});

test('a manual retry cannot overwrite an initial permanent failure', async (t) => {
    const { queue, TestTask } = await setup(t);
    const work = deferred();
    const failure = new Error('Rejected');
    const task = new TestTask({ operation: () => work.promise });
    const rejected = assert.rejects(queue.submit(task), (error) => error === failure);
    await flush();
    queue.retry(task.id);
    work.reject(failure);
    await rejected;
    await flush();
    assert.equal(task.calls, 1);
    assert.equal(queue.get(task.id), undefined);
});

test('offline submissions start concurrently on reconnect', async (t) => {
    const { queue, TestTask, connect } = await setup(t, { online: false });
    const first = new TestTask({ operation: untilAborted });
    const second = new TestTask({ operation: untilAborted });
    enqueue(queue, first);
    enqueue(queue, second);
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
    enqueue(queue, task);
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
    enqueue(queue, task);
    await flush();
    assert.equal(task.state.status, 'waiting');

    const other = new TestTask();
    enqueue(queue, other);
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
        connect(false);
        await enqueue(queue, task);
        connect(true);
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
    enqueue(queue, task);
    assert.throws(() => enqueue(queue, task), /already enqueued/);
    assert.throws(() => enqueue(queue, new TestTask({ ownerId: 'other' })), /another account/);
    await flush();
    assert.throws(() => enqueue(queue, task), /Only queued tasks/);
    queue.retry('missing');
    await queue.cancel('missing');
});

test('cancellation waits for late work without blocking other tasks or accepting late success', async (t) => {
    const { queue, TestTask } = await setup(t);
    const work = deferred();
    const first = new TestTask({ operation: () => work.promise });
    enqueue(queue, first);
    await flush();
    const cancellation = queue.cancel(first.id);
    const second = new TestTask({ operation: untilAborted });
    enqueue(queue, second);
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
    enqueue(queue, task);
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
    enqueue(queue, task);
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
    enqueue(queue, task);
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

test('account changes synchronously hide and suspend previous tasks', async (t) => {
    const { queue, TestTask, setAuth } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    enqueue(queue, task);
    await flush();
    setAuth('other', true);
    assert.equal(queue.pendingCount, 0);
    assert.equal(task.signal.aborted, true);
    assert.throws(() => enqueue(queue, new TestTask()), /another account/);
    const next = new TestTask({ ownerId: 'other' });
    enqueue(queue, next);
    await flush();
    assert.equal(task.state.status, 'queued');
    assert.equal(next.state.status, 'completed');
});

test('focus detects expired auth and renewed auth resumes queued work', async (t) => {
    const { queue, TestTask, setAuth, browserWindow } = await setup(t);
    const task = new TestTask({
        operation: async (signal, current) => {
            if (current.calls === 1) await untilAborted(signal);
        },
    });
    enqueue(queue, task);
    await flush();
    setAuth('owner', false, false);
    browserWindow.dispatchEvent(new Event('focus'));
    await flush();
    assert.equal(queue.authenticationRequired, true);
    assert.equal(task.state.status, 'queued');
    assert.throws(() => enqueue(queue, new TestTask()), /Sign in/);
    setAuth('owner', true);
    await flush();
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'completed');
});

test('disposal suspends tasks, removes listeners, and prevents pending execution', async (t) => {
    const { queue, TestTask, connect, authListeners } = await setup(t);
    const task = new TestTask({ operation: untilAborted });
    enqueue(queue, task);
    await flush();
    const pending = new TestTask();
    enqueue(queue, pending);
    queue.$dispose();
    assert.equal(authListeners.size, 0);
    assert.equal(queue.pendingCount, 0);
    connect(false);
    assert.equal(queue.isOnline, true);
    await flush();
    assert.equal(task.state.status, 'queued');
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
    enqueue(queue, task);
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

test('admission waits for a committed create before starting or returning queued success', async (t) => {
    const { queue, database, TestTask, connect } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (value) => {
        await commit.promise;
        await create(value);
    });
    const task = new TestTask();
    let settled = false;
    const submission = queue.submit(task).then((result) => {
        settled = true;
        return result;
    });
    await flush();
    assert.equal(settled, false);
    assert.equal(task.calls, 0);
    commit.resolve();
    assert.equal((await submission).status, 'queued');
    assert.equal(database.records.has(database.key(task.ownerId, task.id)), true);
    connect(true);
    await flush();
    assert.equal(task.calls, 1);
});

test('quota and unavailable storage reject admission without sending a request', async (t) => {
    const { queue, database, TestTask, taskModule } = await setup(t);
    t.mock.method(database, 'create', async () => {
        throw new DOMException('Full', 'QuotaExceededError');
    });
    const task = new TestTask();
    await assert.rejects(
        queue.submit(task),
        (error) => error instanceof taskModule.TaskPersistenceError,
    );
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.match(queue.storageError, /Full/);
    assert.equal(database.records.size, 0);
});

test('a failed checkpoint keeps the task blocked until a successful save on manual retry', async (t) => {
    const { queue, database, TestTask, taskModule } = await setup(t);
    const save = database.save.bind(database);
    let failing = true;
    t.mock.method(database, 'save', async (snapshot) => {
        if (failing) throw new Error('Storage offline');
        await save(snapshot);
    });
    const task = new TestTask();
    await assert.rejects(
        queue.submit(task),
        (error) => error instanceof taskModule.TaskPersistenceError,
    );
    assert.equal(task.calls, 0);
    assert.equal(task.state.status, 'blocked');
    assert.equal(queue.get(task.id), task);
    failing = false;
    await queue.retry(task.id);
    assert.equal(task.calls, 1);
    assert.equal(task.state.status, 'completed');
    assert.equal(database.records.size, 0);
});

test('a committed terminal marker prevents replay when deletion fails', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t);
    const remove = database.delete.bind(database);
    let failing = true;
    t.mock.method(database, 'delete', async (...args) => {
        if (failing) throw new Error('Deletion unavailable');
        return remove(...args);
    });
    const task = new TestTask();
    assert.equal((await queue.submit(task)).status, 'completed');
    assert.equal(
        database.records.get(database.key(task.ownerId, task.id)).state.status,
        'completed',
    );
    failing = false;
    setAuth('other', true);
    await queue.initialize();
    setAuth('owner', true);
    await queue.initialize();
    await flush();
    assert.equal(task.calls, 1);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('sign-out retains tasks per owner and restored blocked tasks require manual retry', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t, { online: false });
    const task = new TestTask();
    await queue.submit(task);
    task.mutableState.status = 'blocked';
    task.mutableState.error = 'Needs authentication';
    await flush();
    setAuth(null, false);
    assert.equal(queue.pendingCount, 0);
    await queue.initialize();
    assert.equal(database.records.size, 1);
    setAuth('other', true);
    await queue.initialize();
    assert.equal(queue.pendingCount, 0);
    setAuth('owner', true);
    await queue.initialize();
    const restored = queue.get(task.id);
    assert.notEqual(restored, task);
    assert.equal(restored.state.status, 'blocked');
    assert.equal(restored.state.error, 'Needs authentication');
    assert.equal(restored.calls, 0);
});

test('clearSaved drains pending writes and cannot recreate records afterward', async (t) => {
    const { queue, database, TestTask } = await setup(t, { online: false });
    const task = new TestTask();
    await queue.submit(task);
    const commit = deferred();
    const save = database.save.bind(database);
    t.mock.method(database, 'save', async (snapshot) => {
        await commit.promise;
        await save(snapshot);
    });
    task.report(1, 10);
    const saving = task.checkpoint();
    await flush();
    const clearing = queue.clearSaved();
    commit.resolve();
    await clearing;
    await saving;
    assert.equal(database.records.size, 0);
    assert.equal(queue.pendingCount, 0);
    task.report(4, 10);
    await flush();
    assert.equal(database.records.size, 0);
    assert.throws(() => queue.submit(new TestTask()), /stopped/);
});

test('progress saves are throttled and cannot overwrite a later durable checkpoint', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const { queue, database, TestTask } = await setup(t, { online: false });
    const task = new TestTask();
    await queue.submit(task);
    for (let bytes = 1; bytes <= 9; bytes++) task.report(bytes, 10);
    await flush();
    assert.equal(database.writes.length, 1);
    t.mock.timers.tick(1000);
    await flush();
    assert.equal(database.writes.length, 2);
    assert.equal(database.writes[1][1].state.progress.completed, 9);
    task.report(10, 10);
    await queue.cancel(task.id);
    t.mock.timers.tick(1000);
    await flush();
    assert.equal(database.records.size, 0);
    assert.equal(database.writes.at(-1)[0], 'delete');
});

test('a failed cancellation retains its intent and is cleaned up after restoration', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t, { online: false });
    const task = new TestTask();
    await queue.submit(task);
    const save = database.save.bind(database);
    let failing = true;
    t.mock.method(database, 'save', async (snapshot) => {
        if (failing) throw new Error('Storage busy');
        return save(snapshot);
    });
    await queue.cancel(task.id);
    assert.equal(task.state.status, 'cancelling');
    assert.equal(queue.get(task.id), task);
    assert.equal(task.calls, 0);
    failing = false;
    setAuth(null, false);
    await queue.initialize();
    assert.equal(
        database.records.get(database.key(task.ownerId, task.id)).state.status,
        'cancelling',
    );
    setAuth('owner', true);
    await queue.initialize();
    assert.equal(queue.get(task.id), undefined);
    assert.equal(database.records.size, 0);
    assert.equal(task.calls, 0);
});

test('cancellation during admission removes the eventual committed record', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (serialized) => {
        await commit.promise;
        return create(serialized);
    });
    const task = new TestTask();
    const rejected = assert.rejects(queue.submit(task), { name: 'AbortError' });
    await flush();
    await queue.cancel(task.id);
    commit.resolve();
    await rejected;
    assert.equal(task.calls, 0);
    assert.equal(database.records.size, 0);
    setAuth('other', true);
    await queue.initialize();
    setAuth('owner', true);
    await queue.initialize();
    assert.equal(queue.pendingCount, 0);
});

test('an account change during admission preserves the record without publishing or executing it', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (serialized) => {
        await commit.promise;
        return create(serialized);
    });
    const task = new TestTask();
    const rejected = assert.rejects(queue.submit(task), { name: 'AbortError' });
    await flush();
    setAuth('other', true);
    commit.resolve();
    await rejected;
    await queue.initialize();
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 1);
    setAuth('owner', true);
    await queue.initialize();
    assert.equal(queue.get(task.id).state.status, 'queued');
});

test('a failed progress checkpoint aborts execution and requires a durable manual retry', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const { queue, database, TestTask, taskModule } = await setup(t);
    const task = new TestTask({
        operation: async (signal, current) => {
            if (current.calls === 1) await untilAborted(signal);
            return 'accepted';
        },
    });
    const rejected = assert.rejects(
        queue.submit(task),
        (error) => error instanceof taskModule.TaskPersistenceError,
    );
    await flush();
    const save = database.save.bind(database);
    let failing = true;
    t.mock.method(database, 'save', async (snapshot) => {
        if (failing) throw new Error('Storage offline');
        return save(snapshot);
    });
    task.report(1, 10);
    t.mock.timers.tick(1000);
    await rejected;
    assert.equal(task.signal.aborted, true);
    assert.equal(task.state.status, 'blocked');
    assert.match(queue.storageError, /Storage offline/);
    await queue.retry(task.id);
    assert.equal(task.calls, 1);
    failing = false;
    await queue.retry(task.id);
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'completed');
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('completion checkpoint failure preserves the result and retries only cleanup', async (t) => {
    const { queue, database, TestTask } = await setup(t);
    const save = database.save.bind(database);
    let failing = true;
    t.mock.method(database, 'save', async (snapshot) => {
        if (failing && snapshot.state.status === 'completed') throw new Error('Storage offline');
        return save(snapshot);
    });
    const completed = [];
    const task = new TestTask({
        operation: async () => 'accepted',
        onCompleted: (result) => completed.push(result),
    });
    assert.equal((await queue.submit(task)).result, 'accepted');
    assert.equal(task.state.status, 'completed');
    assert.equal(task.failure, null);
    assert.equal(queue.get(task.id), task);
    assert.match(queue.storageError, /Storage offline/);
    failing = false;
    await queue.retry(task.id);
    assert.equal(task.calls, 1);
    assert.deepEqual(completed, ['accepted']);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('failed cancellation retries its cleanup without executing the task', async (t) => {
    const { queue, database, TestTask } = await setup(t, { online: false });
    const task = new TestTask();
    await queue.submit(task);
    const save = database.save.bind(database);
    let failing = true;
    t.mock.method(database, 'save', async (snapshot) => {
        if (failing) throw new Error('Storage offline');
        return save(snapshot);
    });
    await queue.cancel(task.id);
    assert.equal(task.state.status, 'cancelling');
    assert.equal(queue.get(task.id), task);
    failing = false;
    // Cleanup retries use the existing task Retry action once online.
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    window.dispatchEvent(new Event('online'));
    await queue.retry(task.id);
    assert.equal(task.state.status, 'cancelled');
    assert.equal(task.calls, 0);
    assert.equal(database.records.size, 0);
});

test('account changes while removing an initial failure still reject with AbortError', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t);
    const deleting = deferred();
    const deleted = deferred();
    const remove = database.delete.bind(database);
    t.mock.method(database, 'delete', async (...args) => {
        deleting.resolve();
        await deleted.promise;
        return remove(...args);
    });
    const task = new TestTask({
        operation: async () => {
            throw new Error('Rejected');
        },
    });
    const rejected = assert.rejects(queue.submit(task), { name: 'AbortError' });
    await deleting.promise;
    setAuth('other', true);
    deleted.resolve();
    await rejected;
    await queue.initialize();
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('background submission waits for admission but not the first attempt', async (t) => {
    const { queue, database, TestTask } = await setup(t);
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (snapshot) => {
        await commit.promise;
        await create(snapshot);
    });
    const task = new TestTask({ operation: untilAborted });
    let settled = false;
    const submission = queue.submit(task, { waitForFirstTry: false }).then((outcome) => {
        settled = true;
        return outcome;
    });
    await flush();
    assert.equal(settled, false);
    assert.equal(task.calls, 0);
    assert.equal(database.records.size, 0);

    commit.resolve();
    assert.deepEqual(await submission, { status: 'queued', taskId: task.id });
    await flush();
    assert.equal(queue.get(task.id), task);
    assert.equal(database.records.has(database.key(task.ownerId, task.id)), true);
    assert.equal(task.calls, 1);
    assert.equal(task.state.status, 'running');
    await queue.cancel(task.id);
});

test('offline background submission resolves and reconnect starts execution', async (t) => {
    const { queue, database, TestTask, connect } = await setup(t, { online: false });
    const task = new TestTask({ operation: untilAborted });
    assert.deepEqual(await queue.submit(task, { waitForFirstTry: false }), {
        status: 'queued',
        taskId: task.id,
    });
    assert.equal(task.calls, 0);
    assert.equal(task.state.status, 'queued');
    assert.equal(database.records.has(database.key(task.ownerId, task.id)), true);
    connect(true);
    await flush();
    assert.equal(task.calls, 1);
    assert.equal(task.state.status, 'running');
    await queue.cancel(task.id);
});

test('background failures stay durable and manual retry uses the same task', async (t) => {
    const { queue, database, TestTask } = await setup(t);
    const failure = new Error('Transfer rejected');
    const task = new TestTask({
        operation: async (_signal, current) => {
            if (current.calls === 1) throw failure;
            return 'accepted';
        },
    });
    assert.equal((await queue.submit(task, { waitForFirstTry: false })).status, 'queued');
    await flush();
    assert.equal(task.state.status, 'failed');
    assert.equal(task.failure, failure);
    assert.equal(queue.get(task.id), task);
    assert.equal(database.records.get(database.key(task.ownerId, task.id)).state.status, 'failed');
    await queue.retry(task.id);
    assert.equal(task.calls, 2);
    assert.equal(task.state.status, 'completed');
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('background admission rejects storage failure without starting execution', async (t) => {
    const { queue, database, TestTask, taskModule } = await setup(t);
    t.mock.method(database, 'create', async () => {
        throw new DOMException('Full', 'QuotaExceededError');
    });
    const task = new TestTask();
    await assert.rejects(
        queue.submit(task, { waitForFirstTry: false }),
        (error) => error instanceof taskModule.TaskPersistenceError,
    );
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('a background checkpoint failure cannot reject successful admission', async (t) => {
    const { queue, database, TestTask } = await setup(t);
    t.mock.method(database, 'save', async () => {
        throw new Error('Storage unavailable');
    });
    const task = new TestTask();
    assert.equal((await queue.submit(task, { waitForFirstTry: false })).status, 'queued');
    await flush();
    assert.equal(task.calls, 0);
    assert.equal(task.state.status, 'blocked');
    assert.equal(queue.get(task.id), task);
    assert.match(queue.storageError, /Storage unavailable/);
});

test('background submission rejects duplicate IDs during admission', async (t) => {
    const { queue, database, TestTask } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (snapshot) => {
        await commit.promise;
        await create(snapshot);
    });
    const task = new TestTask();
    const submission = queue.submit(task, { waitForFirstTry: false });
    assert.throws(() => queue.submit(task, { waitForFirstTry: false }), /already enqueued/);
    assert.throws(
        () => queue.submit(new TestTask({ id: task.id }), { waitForFirstTry: false }),
        /already enqueued/,
    );
    commit.resolve();
    await submission;
    assert.equal(database.records.size, 1);
});

test('cancellation during background admission removes the committed record', async (t) => {
    const { queue, database, TestTask } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (snapshot) => {
        await commit.promise;
        await create(snapshot);
    });
    const task = new TestTask();
    const rejected = assert.rejects(queue.submit(task, { waitForFirstTry: false }), {
        name: 'AbortError',
    });
    await flush();
    await queue.cancel(task.id);
    commit.resolve();
    await rejected;
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
});

test('account changes during background admission retain the old account record', async (t) => {
    const { queue, database, TestTask, setAuth } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (snapshot) => {
        await commit.promise;
        await create(snapshot);
    });
    const task = new TestTask();
    const rejected = assert.rejects(queue.submit(task, { waitForFirstTry: false }), {
        name: 'AbortError',
    });
    await flush();
    setAuth('other', true);
    commit.resolve();
    await rejected;
    await queue.initialize();
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 1);
    setAuth('owner', true);
    await queue.initialize();
    assert.equal(queue.get(task.id).state.status, 'queued');
});

test('clearSaved drains background admission before erasing records', async (t) => {
    const { queue, database, TestTask } = await setup(t, { online: false });
    const commit = deferred();
    const create = database.create.bind(database);
    t.mock.method(database, 'create', async (snapshot) => {
        await commit.promise;
        await create(snapshot);
    });
    const task = new TestTask();
    const rejected = assert.rejects(queue.submit(task, { waitForFirstTry: false }), {
        name: 'AbortError',
    });
    await flush();
    const clearing = queue.clearSaved();
    commit.resolve();
    await rejected;
    await clearing;
    assert.equal(task.calls, 0);
    assert.equal(queue.pendingCount, 0);
    assert.equal(database.records.size, 0);
    assert.throws(() => queue.submit(new TestTask(), { waitForFirstTry: false }), /stopped/);
});
