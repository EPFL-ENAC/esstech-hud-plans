import { defineStore } from 'pinia';
import { computed, markRaw, onScopeDispose, shallowReactive } from 'vue';
import { useAuthentication } from 'src/composables/useAuthentication';
import { useOnlineConnection } from 'src/composables/useOnlineConnection';
import type { NetworkDependentTask } from 'src/lib/networkDependentTasks';

export type TaskSubmission<TResult> =
    | { status: 'completed'; taskId: string; result: TResult }
    | { status: 'queued'; taskId: string };

export const useNetworkDependentTasks = defineStore('networkDependentTasks', () => {
    const entries = shallowReactive(new Map<string, NetworkDependentTask<unknown>>());
    const tasks = computed<readonly NetworkDependentTask<unknown>[]>(() => [...entries.values()]);
    // Reconnect/manual retries wait until submit has captured the initial outcome.
    const submissions = new Map<string, Promise<unknown>>();
    const pendingCount = computed(() => entries.size);
    const auth = useAuthentication({
        onChange(current, previous) {
            if (current.ownerId !== previous.ownerId) {
                void clear();
            } else if (!current.isAuthenticated) {
                void pauseRunningTasks();
            } else {
                resumeTasks();
            }
        },
    });
    const authenticationRequired = computed(() => !auth.isAuthenticated.value);

    const { isOnline } = useOnlineConnection({
        onOnline: () => resumeTasks(true),
        onOffline: () => {
            void pauseRunningTasks();
        },
    });

    async function runAttempt<TResult>(
        task: NetworkDependentTask<TResult>,
    ): Promise<TResult | undefined> {
        await task.waitUntilIdle();
        if (!auth.refreshAuthentication() || !isOnline.value || entries.get(task.id) !== task) {
            return;
        }

        const result = await task.retryOrResume();
        await task.waitUntilIdle();
        if (task.state.status === 'completed' && entries.get(task.id) === task) {
            entries.delete(task.id);
        }
        return result;
    }

    async function execute(
        task: NetworkDependentTask<unknown>,
        retry: 'none' | 'waiting' | 'all' = 'none',
    ): Promise<void> {
        // A rejected initial attempt is removed by submit; do not replay it.
        await submissions.get(task.id)?.catch(() => undefined);
        await task.waitUntilIdle();
        if (entries.get(task.id) !== task) return;
        if (retry === 'all' || (retry === 'waiting' && task.state.status === 'waiting')) {
            task.requestRetry();
        }
        await runAttempt(task);
    }

    async function submitNow<TResult>(
        task: NetworkDependentTask<TResult>,
    ): Promise<TaskSubmission<TResult>> {
        const result = await runAttempt(task);
        if (
            auth.ownerId.value !== task.ownerId ||
            task.state.status === 'cancelled' ||
            task.state.status === 'cancelling' ||
            (task.state.status !== 'completed' && entries.get(task.id) !== task)
        ) {
            throw new DOMException('Task submission was cancelled', 'AbortError');
        }
        if (task.state.status === 'completed') {
            // The completed lifecycle state guarantees a result, including void.
            return { status: 'completed', taskId: task.id, result: result as TResult };
        }
        if (task.state.status === 'blocked' || task.state.status === 'failed') {
            entries.delete(task.id);
            throw task.failure;
        }
        return { status: 'queued', taskId: task.id };
    }

    function submit<TResult>(
        task: NetworkDependentTask<TResult>,
    ): Promise<TaskSubmission<TResult>> {
        if (!auth.refreshAuthentication()) throw new Error('Sign in before submitting tasks');
        if (task.ownerId !== auth.ownerId.value) throw new Error('Task belongs to another account');
        if (entries.has(task.id)) throw new Error('Task is already enqueued');
        if (task.state.status !== 'queued') {
            throw new Error('Only queued tasks can be submitted');
        }

        entries.set(task.id, markRaw(task));
        if (!isOnline.value) return Promise.resolve({ status: 'queued', taskId: task.id });

        const submission = submitNow(task).finally(() => submissions.delete(task.id));
        submissions.set(task.id, submission);
        return submission;
    }

    function get(id: string): NetworkDependentTask<unknown> | undefined {
        return entries.get(id);
    }

    function retry(id: string): void {
        if (!auth.refreshAuthentication() || !isOnline.value) return;
        const task = entries.get(id);
        if (!task) return;
        void execute(task, 'all');
    }

    async function cancel(id: string): Promise<void> {
        const task = entries.get(id);
        if (!task) return;
        await task.cancel();
        if (entries.get(id) === task) entries.delete(id);
    }

    async function clear(): Promise<void> {
        const previousTasks = [...entries.values()];
        entries.clear();
        await Promise.all(previousTasks.map((task) => task.cancel()));
    }

    async function pauseRunningTasks(): Promise<void> {
        await Promise.all(
            [...entries.values()]
                .filter(
                    (task) => task.state.status === 'running' || task.state.status === 'pausing',
                )
                .map((task) => task.pause()),
        );
    }

    function resumeTasks(retryWaiting = false): void {
        if (!auth.refreshAuthentication() || !isOnline.value) return;
        for (const task of entries.values()) {
            if (
                task.state.status === 'queued' ||
                task.state.status === 'pausing' ||
                (retryWaiting && task.state.status === 'waiting')
            ) {
                void execute(task, retryWaiting ? 'waiting' : 'none');
            }
        }
    }

    onScopeDispose(() => {
        void clear();
    });

    return {
        tasks,
        pendingCount,
        isOnline,
        authenticationRequired,
        submit,
        get,
        retry,
        cancel,
        clear,
    };
});
