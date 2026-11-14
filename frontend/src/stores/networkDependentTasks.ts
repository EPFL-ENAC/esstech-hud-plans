import { defineStore } from 'pinia';
import { computed, markRaw, onScopeDispose, shallowReactive } from 'vue';
import { useAuthentication } from 'src/composables/useAuthentication';
import { useOnlineConnection } from 'src/composables/useOnlineConnection';
import type { NetworkDependentTask } from 'src/lib/networkDependentTasks';

export const useNetworkDependentTasks = defineStore('networkDependentTasks', () => {
    const entries = shallowReactive(new Map<string, NetworkDependentTask>());
    const tasks = computed<readonly NetworkDependentTask[]>(() => [...entries.values()]);
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

    async function execute(task: NetworkDependentTask): Promise<void> {
        await task.waitUntilIdle();
        if (!auth.refreshAuthentication() || !isOnline.value || entries.get(task.id) !== task) {
            return;
        }

        await task.retryOrResume();
        await task.waitUntilIdle();
        if (task.state.status === 'completed' && entries.get(task.id) === task) {
            entries.delete(task.id);
        }
    }

    function submit(task: NetworkDependentTask): string {
        if (!auth.refreshAuthentication()) throw new Error('Sign in before submitting tasks');
        if (task.ownerId !== auth.ownerId.value) throw new Error('Task belongs to another account');
        if (entries.has(task.id)) throw new Error('Task is already enqueued');
        if (task.state.status !== 'queued') {
            throw new Error('Only queued tasks can be submitted');
        }

        entries.set(task.id, markRaw(task));
        void execute(task);
        return task.id;
    }

    function get(id: string): NetworkDependentTask | undefined {
        return entries.get(id);
    }

    function retry(id: string): void {
        if (!auth.refreshAuthentication() || !isOnline.value) return;
        const task = entries.get(id);
        if (!task) return;
        task.requestRetry();
        void execute(task);
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
            if (retryWaiting && task.state.status === 'waiting') task.requestRetry();
            if (task.state.status === 'queued' || task.state.status === 'pausing') {
                void execute(task);
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
