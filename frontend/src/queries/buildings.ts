import type { Page } from 'src/lib/pagination';
import { useQuery } from '@pinia/colada';
import {
    computed,
    onActivated,
    onDeactivated,
    onMounted,
    onScopeDispose,
    ref,
    toValue,
    watch,
    type MaybeRefOrGetter,
    type Ref,
} from 'vue';
import { useDocumentVisibility } from 'src/composables/useDocumentVisibility';
import { getAuthSubject } from 'src/lib/auth';
import {
    getBuilding,
    isReconstructionProcessing,
    listBuildingLocations,
    listBuildings,
    type BuildingListItem,
    type ReconstructionStatusFilter,
} from 'src/lib/buildings';

export const MY_BUILDINGS_PAGE_SIZE = 20;

export function useAllBuildingsQuery() {
    const subject = getAuthSubject();

    return useQuery({
        key: ['buildings', subject, 'all'],
        enabled: () => subject !== null,
        query: async () => {
            const buildings: BuildingListItem[] = [];
            const limit = 100;
            let page: Page<BuildingListItem>;
            do {
                page = await listBuildings({ offset: buildings.length, limit });
                buildings.push(...page.items);
            } while (page.items.length > 0 && buildings.length < page.total);
            return buildings;
        },
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });
}

export function useBuildingLocationsQuery() {
    const subject = getAuthSubject();
    const active = ref(true);
    const visible = ref(document.visibilityState === 'visible');
    const enabled = computed(() => subject !== null && active.value && visible.value);
    const query = useQuery({
        key: ['buildings', subject, 'locations'],
        enabled,
        query: listBuildingLocations,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });

    function updateVisibility() {
        visible.value = document.visibilityState === 'visible';
    }

    onMounted(() => document.addEventListener('visibilitychange', updateVisibility));
    onActivated(() => {
        active.value = true;
        if (enabled.value) void query.refresh();
    });
    onDeactivated(() => {
        active.value = false;
    });
    onScopeDispose(() => document.removeEventListener('visibilitychange', updateVisibility));

    return query;
}

export function useBuildingQuery(buildingId: Ref<string>) {
    const subject = getAuthSubject();

    return useQuery({
        key: () => ['buildings', subject, 'detail', buildingId.value],
        enabled: () => subject !== null && buildingId.value !== '',
        query: () => getBuilding(buildingId.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });
}

export function useMyBuildingsQuery(
    offset: Ref<number>,
    reconstructionStatus?: MaybeRefOrGetter<ReconstructionStatusFilter | null | undefined>,
    search?: MaybeRefOrGetter<string | null | undefined>,
) {
    const subject = getAuthSubject();
    const active = ref(true);
    const visible = useDocumentVisibility();
    const enabled = () =>
        subject !== null && getAuthSubject() === subject && active.value && visible.value;
    const options = computed(() => ({
        offset: offset.value,
        limit: MY_BUILDINGS_PAGE_SIZE,
        sort_order: 'desc' as const,
        reconstruction_status: toValue(reconstructionStatus) ?? null,
        search: toValue(search)?.trim() || null,
    }));

    onActivated(() => {
        active.value = true;
    });
    onDeactivated(() => {
        active.value = false;
    });

    const query = useQuery({
        key: () => ['buildings', subject, 'list', options.value],
        enabled,
        query: () => listBuildings(options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        autoRefetch: (state) =>
            state.data?.items.some((item) =>
                isReconstructionProcessing(item.latest_reconstruction?.status),
            )
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
        [options, enabled],
        () => {
            // A poll that finishes off-page leaves no timer for a fresh cached entry.
            if (
                enabled() &&
                !query.isLoading.value &&
                query.data.value?.items.some((item) =>
                    isReconstructionProcessing(item.latest_reconstruction?.status),
                )
            ) {
                void query.refetch();
            }
        },
        { immediate: true, flush: 'post' },
    );

    return { ...query, isForegroundLoading, refetch };
}
