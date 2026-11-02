import { useQuery, useQueryCache } from '@pinia/colada';
import { computed, onActivated, onDeactivated, ref, watch, type Ref } from 'vue';
import { useDocumentVisibility } from 'src/composables/useDocumentVisibility';
import { getAuthSubject } from 'src/lib/auth';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { useSplatDownloadStore } from 'src/stores/splatDownload';
import { useVideoDownloadStore } from 'src/stores/videoDownload';
import {
    getReconstructionPointCloud,
    getReconstructionPointCloudMeta,
    getReconstructionSplat,
    getReconstructionStep,
    getReconstructionVideo,
    isReconstructionProcessing,
    listReconstructions,
    type ReconstructionPointCloudMeta,
} from 'src/lib/buildings';

export const RECONSTRUCTIONS_PAGE_SIZE = 20;

function reconstructionKey(subject: string | null, buildingId: string) {
    return ['buildings', subject, 'detail', buildingId, 'reconstructions'] as const;
}

export function useReconstructionsQuery(buildingId: Ref<string>, offset: Ref<number>) {
    const subject = getAuthSubject();
    const active = ref(true);
    const visible = useDocumentVisibility();
    const enabled = () =>
        subject !== null &&
        getAuthSubject() === subject &&
        buildingId.value !== '' &&
        active.value &&
        visible.value;
    const options = computed(() => ({
        offset: offset.value,
        limit: RECONSTRUCTIONS_PAGE_SIZE,
        sort_order: 'desc' as const,
    }));

    onActivated(() => {
        active.value = true;
    });
    onDeactivated(() => {
        active.value = false;
    });

    const query = useQuery({
        key: () => [...reconstructionKey(subject, buildingId.value), 'list', options.value],
        enabled,
        query: () => listReconstructions(buildingId.value, options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        autoRefetch: (state) =>
            state.data?.items.some((item) => isReconstructionProcessing(item.status))
                ? 5_000
                : false,
    });

    const manualRefreshing = ref(false);
    const isForegroundLoading = computed(
        () => query.isLoading.value && (query.data.value === undefined || manualRefreshing.value),
    );
    const refetch: typeof query.refetch = async (throwOnError) => {
        manualRefreshing.value = true;
        try {
            return await query.refetch(throwOnError);
        } finally {
            manualRefreshing.value = false;
        }
    };

    watch(
        [buildingId, options, enabled],
        () => {
            // A poll that finishes off-page leaves no timer for a fresh cached entry.
            if (
                enabled() &&
                !query.isLoading.value &&
                query.data.value?.items.some((item) => isReconstructionProcessing(item.status))
            ) {
                void query.refetch();
            }
        },
        { immediate: true, flush: 'post' },
    );

    return { ...query, isForegroundLoading, refetch };
}

export function useReconstructionStepQuery(buildingId: Ref<string>, reconstructionId: Ref<string>) {
    const enabled = computed(() => buildingId.value !== '' && reconstructionId.value !== '');
    return useQuery({
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
        autoRefetch: 5_000,
    });
}

export function useReconstructionVideoQuery(
    buildingId: Ref<string>,
    reconstructionId: Ref<string>,
) {
    const subject = getAuthSubject();
    const cache = useQueryCache();
    const videoDownload = useVideoDownloadStore();
    const key = computed(() => [
        ...reconstructionKey(subject, buildingId.value),
        'video',
        reconstructionId.value,
    ]);
    // A different building or reconstruction must restart the progress bar.
    watch([buildingId, reconstructionId], () => videoDownload.reset());
    const query = useQuery({
        key: () => key.value,
        enabled: false,
        query: ({ signal }) => {
            videoDownload.reset();
            return getReconstructionVideo(
                buildingId.value,
                reconstructionId.value,
                signal,
                (progress) => videoDownload.update(progress),
            );
        },
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

export interface ReconstructionPointCloudData {
    buffer: ArrayBuffer;
    meta: ReconstructionPointCloudMeta | null;
}

export function useReconstructionPointCloudQuery(
    buildingId: Ref<string>,
    reconstructionId: Ref<string>,
) {
    const subject = getAuthSubject();
    const splatDownload = useSplatDownloadStore();

    // A different building or reconstruction must restart the progress bar.
    watch([buildingId, reconstructionId], () => splatDownload.reset());

    function reportProgress(progress: FetchProgress): void {
        splatDownload.update(progress);
    }

    return useQuery({
        key: () => [
            ...reconstructionKey(subject, buildingId.value),
            'point-cloud',
            reconstructionId.value,
        ],
        enabled: () => subject !== null && buildingId.value !== '' && reconstructionId.value !== '',
        query: ({ signal }) => {
            splatDownload.reset();
            return Promise.all([
                getReconstructionPointCloud(
                    buildingId.value,
                    reconstructionId.value,
                    signal,
                    reportProgress,
                ),
                getReconstructionPointCloudMeta(
                    buildingId.value,
                    reconstructionId.value,
                    signal,
                ).catch(() => null),
            ]).then(([buffer, meta]) => ({ buffer, meta }));
        },
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
}

export function useReconstructionSplatQuery(
    buildingId: Ref<string>,
    reconstructionId: Ref<string>,
) {
    const subject = getAuthSubject();
    const splatDownload = useSplatDownloadStore();

    // A different building or reconstruction must restart the progress bar.
    watch([buildingId, reconstructionId], () => splatDownload.reset());

    function reportProgress(progress: FetchProgress): void {
        splatDownload.update(progress);
    }

    return useQuery({
        key: () => [
            ...reconstructionKey(subject, buildingId.value),
            'splat',
            reconstructionId.value,
        ],
        enabled: () => subject !== null && buildingId.value !== '' && reconstructionId.value !== '',
        query: ({ signal }) => {
            splatDownload.reset();
            return getReconstructionSplat(
                buildingId.value,
                reconstructionId.value,
                signal,
                reportProgress,
            );
        },
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
}
