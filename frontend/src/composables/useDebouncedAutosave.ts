import { onScopeDispose, readonly, ref, watch } from 'vue';

type SaveStatus = 'saved' | 'saving' | 'error';

export function useDebouncedAutosave<T>(
    source: () => T | undefined,
    save: (value: T) => Promise<void>,
    delayMs: number,
) {
    const status = ref<SaveStatus>('saved');
    let timer: ReturnType<typeof setTimeout> | undefined;
    let pending = false;
    let inFlight: Promise<void> | undefined;

    function clearTimer(): void {
        clearTimeout(timer);
        timer = undefined;
    }

    function clearPending(): void {
        clearTimer();
        pending = false;
    }

    function finishSave(result: 'saved' | 'error'): void {
        inFlight = undefined;
        if (!pending) status.value = result;
        else if (timer === undefined) void savePending();
    }

    function savePending(): Promise<void> | undefined {
        if (inFlight || !pending) return inFlight;
        pending = false;
        const value = source();
        if (value === undefined) {
            status.value = 'saved';
            return;
        }

        inFlight = Promise.resolve()
            .then(() => save(value))
            .then(
                () => finishSave('saved'),
                () => finishSave('error'),
            );
        return inFlight;
    }

    async function flush(): Promise<void> {
        while (pending || inFlight) {
            clearTimer();
            await savePending();
        }
    }

    async function retry(): Promise<void> {
        if (status.value !== 'error') return;
        pending = true;
        status.value = 'saving';
        await flush();
    }

    watch(
        source,
        (value, previous) => {
            if (value === undefined) {
                clearPending();
                if (!inFlight) status.value = 'saved';
                return;
            }
            if (previous === undefined) return;

            pending = true;
            status.value = 'saving';
            clearTimer();
            timer = setTimeout(() => {
                timer = undefined;
                void savePending();
            }, delayMs);
        },
        { deep: true, flush: 'sync' },
    );
    onScopeDispose(clearPending);

    return { status: readonly(status), flush, retry };
}
