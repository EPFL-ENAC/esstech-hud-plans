import { defineStore } from 'pinia';
import { computed, markRaw, onScopeDispose, readonly, ref, shallowReactive } from 'vue';
import { useAuthentication } from 'src/composables/useAuthentication';
import { useOnlineConnection } from 'src/composables/useOnlineConnection';
import { TaskPersistenceError, type NetworkDependentTask } from 'src/lib/networkDependentTasks';
import { LocalUploadsRegistry } from 'src/lib/localUploadsRegistry';
import { TasksDatabase } from 'src/lib/tasksDatabase';
import { deserializeTask } from 'src/lib/taskRegistry';

export type TaskSubmission<TResult> =
    | { status: 'completed'; taskId: string; result: TResult }
    | { status: 'queued'; taskId: string };

export interface SubmitTaskOptions {
    waitForFirstTry?: boolean;
}

type AnyTask = NetworkDependentTask<unknown>;

function aborted(): DOMException {
    return new DOMException('Task submission was interrupted', 'AbortError');
}

export const useNetworkDependentTasks = defineStore('networkDependentTasks', () => {
    const database = new TasksDatabase();
    const uploads = new LocalUploadsRegistry();
    const entries = shallowReactive(new Map<string, AnyTask>());
    const pendingSubmissions = new Map<AnyTask, Promise<unknown>>();
    // Only failed checkpoints need to survive account suspension in memory.
    const retained = new Set<AnyTask>();
    const tasks = computed<readonly AnyTask[]>(() => [...entries.values()]);
    const pendingCount = computed(() => entries.size);
    const isRestoring = ref(false);
    const reportedError = ref<TaskPersistenceError | null>(null);
    const storageError = computed(() => {
        const failure =
            tasks.value.find((task) => task.storageFailure)?.storageFailure ?? reportedError.value;
        if (!failure) return null;
        return failure.cause instanceof Error
            ? `${failure.message} ${failure.cause.message}`
            : failure.message;
    });
    let requestedOwner: string | null | undefined;
    let generation = 0;
    let restoration = Promise.resolve();
    let restoreFailure: TaskPersistenceError | null = null;
    let stopped = false;

    const auth = useAuthentication({
        onChange(current, previous) {
            if (current.ownerId !== previous.ownerId) {
                void initialize();
            } else if (!current.isAuthenticated) {
                void pauseRunningTasks();
            } else {
                void initialize().then(() => resumeTasks());
            }
        },
    });
    const authenticationRequired = computed(() => !auth.isAuthenticated.value);
    const { isOnline } = useOnlineConnection({
        onOnline: () => {
            void initialize().then(() => resumeTasks(true));
        },
        onOffline: () => {
            void pauseRunningTasks();
        },
    });

    function report(error: unknown): TaskPersistenceError {
        const failure =
            error instanceof TaskPersistenceError ? error : new TaskPersistenceError(error);
        reportedError.value = failure;
        return failure;
    }

    function attach(task: AnyTask): void {
        task.bindPersistence({
            save: (snapshot) => database.save(snapshot),
            delete: () => database.delete(task.ownerId, task.id),
        });
        task.activate();
        entries.set(task.id, markRaw(task));
    }

    function removeFinished(task: AnyTask): void {
        if (task.storageFailure) return;
        if (
            ['completed', 'cancelled'].includes(task.state.status) &&
            entries.get(task.id) === task
        ) {
            entries.delete(task.id);
        }
    }

    async function suspend(task: AnyTask): Promise<void> {
        try {
            await task.suspend();
        } catch (error) {
            report(error);
        }
        if (task.storageFailure) retained.add(task);
        else retained.delete(task);
    }

    function initialize(): Promise<void> {
        if (stopped) return Promise.resolve();
        const ownerId = auth.ownerId.value;
        if (requestedOwner === ownerId && restoreFailure === null) return restoration;
        requestedOwner = ownerId;
        const epoch = ++generation;
        const previous = new Set([...entries.values(), ...pendingSubmissions.keys(), ...retained]);
        const pending = [...pendingSubmissions.values()];
        entries.clear();
        isRestoring.value = true;
        restoreFailure = null;
        // Abort the old account immediately, even during an earlier restoration.
        const suspension = Promise.all([...previous].map(suspend));
        restoration = restoration
            .then(async () => {
                await suspension;
                await Promise.allSettled(pending);
                if (epoch !== generation || stopped || ownerId === null) return;
                const records = await database.list(ownerId);
                reportedError.value = null;
                for (const snapshot of records) {
                    if (epoch !== generation || stopped) return;
                    try {
                        const saved = [...retained].find(
                            (task) => task.ownerId === ownerId && task.id === snapshot.id,
                        );
                        if (
                            ['completed', 'cancelled', 'cancelling'].includes(snapshot.state.status)
                        ) {
                            await database.delete(ownerId, snapshot.id);
                            if (saved) retained.delete(saved);
                            continue;
                        }
                        if (saved) {
                            retained.delete(saved);
                            attach(saved);
                            continue;
                        }
                        const task = deserializeTask(snapshot, uploads);
                        if (epoch !== generation || stopped) return;
                        attach(task);
                    } catch (error) {
                        // Unsupported records remain stored.
                        if (epoch === generation && !stopped) report(error);
                    }
                }
            })
            .catch((error: unknown) => {
                if (epoch === generation) restoreFailure = report(error);
            })
            .finally(() => {
                if (epoch === generation) {
                    isRestoring.value = false;
                    resumeTasks(true);
                }
            });
        return restoration;
    }

    function assertCurrent(task: AnyTask, epoch: number): void {
        if (
            stopped ||
            epoch !== generation ||
            task.ownerId !== auth.ownerId.value ||
            ['cancelled', 'cancelling'].includes(task.state.status)
        )
            throw aborted();
    }

    async function admit(task: AnyTask, epoch: number): Promise<void> {
        assertCurrent(task, epoch);

        try {
            await database.create(task.serialize());
        } catch (error) {
            throw report(error);
        }

        // Bind before checking again so a task committed during an account change
        // can still be suspended or cancelled durably.
        task.bindPersistence({
            save: (snapshot) => database.save(snapshot),
            delete: () => database.delete(task.ownerId, task.id),
        });

        try {
            assertCurrent(task, epoch);
        } catch (error) {
            if (['cancelled', 'cancelling'].includes(task.state.status)) {
                await task.retryPersistence();
                if (task.storageFailure) retained.add(task);
            } else {
                await suspend(task);
            }

            throw error;
        }

        attach(task);
    }

    async function execute<TResult>(
        task: NetworkDependentTask<TResult>,
    ): Promise<TResult | undefined> {
        const result = await task.retryOrResume();
        await task.waitUntilIdle();
        return result;
    }

    function submit<TResult>(
        task: NetworkDependentTask<TResult>,
        { waitForFirstTry = true }: SubmitTaskOptions = {},
    ): Promise<TaskSubmission<TResult>> {
        if (stopped) throw new Error('Task queue is stopped');

        if (!auth.refreshAuthentication()) {
            throw new Error('Sign in before submitting tasks');
        }

        if (task.ownerId !== auth.ownerId.value) {
            throw new Error('Task belongs to another account');
        }

        if (
            entries.has(task.id) ||
            [...pendingSubmissions.keys()].some((entry) => entry.id === task.id)
        ) {
            throw new Error('Task is already enqueued');
        }

        if (task.state.status !== 'queued') {
            throw new Error('Only queued tasks can be submitted');
        }

        const ready = initialize();
        const epoch = generation;

        const submission = (async (): Promise<TaskSubmission<TResult>> => {
            await ready;
            assertCurrent(task, epoch);

            if (restoreFailure) throw restoreFailure;

            await admit(task, epoch);

            const canRun = isOnline.value && auth.refreshAuthentication();
            assertCurrent(task, epoch);

            if (!canRun) {
                return { status: 'queued', taskId: task.id };
            }

            if (!waitForFirstTry) {
                void execute(task)
                    .then(() => {
                        removeFinished(task);
                    })
                    .catch((error: unknown) => {
                        report(error);
                    });

                // This acknowledges durable admission; execution may already be running.
                return { status: 'queued', taskId: task.id };
            }

            const result = await execute(task);
            const status = task.state.status;
            const failure = task.failure;

            assertCurrent(task, epoch);
            removeFinished(task);

            if (status === 'completed') {
                return {
                    status: 'completed',
                    taskId: task.id,
                    result: result as TResult,
                };
            }

            if (task.storageFailure) throw task.storageFailure;

            if (status === 'failed' || status === 'blocked') {
                // Preserve foreground submission behavior: remove an immediately
                // rejected task and reject the caller.
                try {
                    await database.delete(task.ownerId, task.id);
                } catch (error) {
                    report(error);
                }

                if (entries.get(task.id) === task) {
                    entries.delete(task.id);
                }

                assertCurrent(task, epoch);
                throw failure;
            }

            return { status: 'queued', taskId: task.id };
        })().finally(() => {
            pendingSubmissions.delete(task);
        });

        pendingSubmissions.set(task, submission);
        return submission;
    }

    async function resumeTask(task: AnyTask, retryWaiting: boolean): Promise<void> {
        await pendingSubmissions.get(task)?.catch(() => undefined);
        await task.waitUntilIdle();

        if (
            stopped ||
            !auth.refreshAuthentication() ||
            entries.get(task.id) !== task ||
            !isOnline.value ||
            task.storageFailure
        ) {
            return;
        }

        if (retryWaiting && task.state.status === 'waiting') {
            task.requestRetry();
        }

        await execute(task);
        removeFinished(task);
    }

    async function retry(id: string): Promise<void> {
        const task = entries.get(id);

        if (!task || stopped || !isOnline.value || !auth.refreshAuthentication()) {
            return;
        }

        await pendingSubmissions.get(task)?.catch(() => undefined);
        await task.waitUntilIdle();

        if (
            stopped ||
            entries.get(id) !== task ||
            !isOnline.value ||
            !auth.refreshAuthentication()
        ) {
            return;
        }

        if (['completed', 'cancelled', 'cancelling'].includes(task.state.status)) {
            await task.retryPersistence();
        } else {
            task.requestRetry();
            await execute(task);
        }

        removeFinished(task);

        if (!task.storageFailure) {
            reportedError.value = null;
        }
    }

    async function cancel(id: string): Promise<void> {
        const task =
            entries.get(id) ?? [...pendingSubmissions.keys()].find((entry) => entry.id === id);
        if (!task) return;
        await task.cancel();
        removeFinished(task);
    }

    async function clear(): Promise<void> {
        await Promise.all(
            [...new Set([...entries.values(), ...pendingSubmissions.keys()])].map((task) =>
                cancel(task.id),
            ),
        );
    }

    async function clearSaved(): Promise<void> {
        stopped = true;
        ++generation;
        const previous = new Set([...entries.values(), ...pendingSubmissions.keys(), ...retained]);
        entries.clear();
        await Promise.all([...previous].map(suspend));
        await restoration;
        await Promise.allSettled([...pendingSubmissions.values()]);
        retained.clear();
        await database.clearAndClose();
    }

    async function pauseRunningTasks(): Promise<void> {
        await Promise.all(
            [...entries.values()]
                .filter((task) => ['running', 'pausing'].includes(task.state.status))
                .map((task) => task.pause()),
        );
    }

    function resumeTasks(retryWaiting = false): void {
        if (stopped || isRestoring.value || !isOnline.value || !auth.refreshAuthentication())
            return;
        for (const task of entries.values()) {
            if (
                ['queued', 'pausing'].includes(task.state.status) ||
                (retryWaiting && task.state.status === 'waiting')
            ) {
                void resumeTask(task, retryWaiting).catch((error: unknown) => {
                    report(error);
                });
            }
        }
    }

    onScopeDispose(() => {
        stopped = true;
        ++generation;
        const previous = new Set([...entries.values(), ...pendingSubmissions.keys()]);
        entries.clear();
        for (const task of previous) void suspend(task);
    });

    return {
        tasks,
        pendingCount,
        isOnline,
        authenticationRequired,
        isRestoring: readonly(isRestoring),
        storageError,
        initialize,
        submit,
        get: (id: string) => entries.get(id),
        retry,
        cancel,
        clear,
        clearSaved,
    };
});
