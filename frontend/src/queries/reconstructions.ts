import { useQuery, useQueryCache } from '@pinia/colada';
import {
    computed,
    onActivated,
    onDeactivated,
    onMounted,
    onScopeDispose,
    ref,
    watch,
    type Ref,
} from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import {
    getReconstructionSplat,
    getReconstructionStep,
    getReconstructionVideo,
    listReconstructions,
} from 'src/lib/buildings';

export const RECONSTRUCTIONS_PAGE_SIZE = 20;

function reconstructionKey(subject: string | null, buildingId: string) {
    return ['buildings', subject, 'detail', buildingId, 'reconstructions'] as const;
}

export function useReconstructionsQuery(buildingId: Ref<string>, offset: Ref<number>) {
    const subject = getAuthSubject();
    const active = ref(true);
    const visible = ref(document.visibilityState === 'visible');
    const enabled = computed(
        () => subject !== null && buildingId.value !== '' && active.value && visible.value,
    );
    const options = computed(() => ({
        offset: offset.value,
        limit: RECONSTRUCTIONS_PAGE_SIZE + 1,
        sort_order: 'desc' as const,
    }));
    const query = useQuery({
        key: () => [...reconstructionKey(subject, buildingId.value), 'list', options.value],
        enabled,
        query: () => listReconstructions(buildingId.value, options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });

    const isPolling = ref(false);
    let pollingGeneration = 0;
    const isForegroundLoading = computed(() => query.isLoading.value && !isPolling.value);

    function resetPolling() {
        pollingGeneration++;
        isPolling.value = false;
    }

    watch([buildingId, options], resetPolling, { flush: 'sync' });

    const refetch: typeof query.refetch = (throwOnError) => {
        resetPolling();
        return query.refetch(throwOnError);
    };
    const refresh: typeof query.refresh = (throwOnError) => {
        resetPolling();
        return query.refresh(throwOnError);
    };

    async function poll() {
        if (query.isLoading.value) return;

        const generation = ++pollingGeneration;
        isPolling.value = true;
        try {
            await query.refetch();
        } finally {
            // A previous page's poll must not clear a newer poll's marker.
            if (generation === pollingGeneration) isPolling.value = false;
        }
    }

    const shouldPoll = computed(
        () =>
            enabled.value &&
            query.data.value
                ?.slice(0, RECONSTRUCTIONS_PAGE_SIZE)
                .some(
                    ({ status }) =>
                        status === 'preparing' || status === 'scheduled' || status === 'running',
                ) === true,
    );
    let pollingTimer: ReturnType<typeof setInterval> | undefined;
    function stopPolling() {
        clearInterval(pollingTimer);
        pollingTimer = undefined;
    }
    watch(
        shouldPoll,
        (shouldStartPolling) => {
            stopPolling();
            if (shouldStartPolling) {
                pollingTimer = setInterval(() => {
                    if (shouldPoll.value && query.asyncStatus.value !== 'loading') {
                        void poll();
                    }
                }, 5_000);
            }
        },
        { immediate: true },
    );

    function updateVisibility() {
        visible.value = document.visibilityState === 'visible';
    }
    onMounted(() => document.addEventListener('visibilitychange', updateVisibility));
    onActivated(() => {
        active.value = true;
        if (enabled.value) void refresh();
    });
    onDeactivated(() => {
        active.value = false;
        stopPolling();
    });
    onScopeDispose(() => {
        stopPolling();
        document.removeEventListener('visibilitychange', updateVisibility);
    });
    return { ...query, isForegroundLoading, refetch, refresh };
}

export function useReconstructionStepQuery(buildingId: Ref<string>, reconstructionId: Ref<string>) {
    const enabled = computed(() => buildingId.value !== '' && reconstructionId.value !== '');
    const query = useQuery({
        key: () => [
            ...reconstructionKey(getAuthSubject(), buildingId.value),
            'splat',
            reconstructionId.value,
            'step',
        ],
        enabled,
        query: ({ signal }) =>
            getReconstructionStep(buildingId.value, reconstructionId.value, signal),
        staleTime: 0,
    });

    let pollingTimer: ReturnType<typeof setInterval> | undefined;
    function stopPolling() {
        clearInterval(pollingTimer);
        pollingTimer = undefined;
    }
    watch(
        enabled,
        (shouldStartPolling) => {
            stopPolling();
            if (shouldStartPolling) {
                pollingTimer = setInterval(() => {
                    if (enabled.value && query.asyncStatus.value !== 'loading') {
                        void query.refetch();
                    }
                }, 5_000);
            }
        },
        { immediate: true },
    );
    onScopeDispose(stopPolling);

    return query;
}

export function useReconstructionVideoQuery(
    buildingId: Ref<string>,
    reconstructionId: Ref<string>,
) {
    const subject = getAuthSubject();
    const cache = useQueryCache();
    const key = computed(() => [
        ...reconstructionKey(subject, buildingId.value),
        'video',
        reconstructionId.value,
    ]);
    const query = useQuery({
        key: () => key.value,
        enabled: false,
        query: ({ signal }) =>
            getReconstructionVideo(buildingId.value, reconstructionId.value, signal),
        staleTime: Infinity,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
    function cancel() {
        cache.cancelQueries({ key: key.value, exact: true });
    }
    return { ...query, cancel };
}

export function useReconstructionSplatQuery(
    buildingId: Ref<string>,
    reconstructionId: Ref<string>,
) {
    const subject = getAuthSubject();

    return useQuery({
        key: () => [
            ...reconstructionKey(subject, buildingId.value),
            'splat',
            reconstructionId.value,
        ],
        enabled: () => subject !== null && buildingId.value !== '' && reconstructionId.value !== '',
        query: ({ signal }) =>
            getReconstructionSplat(buildingId.value, reconstructionId.value, signal),
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
}
