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
import { getAuthSubject } from 'src/lib/auth';
import {
    getBuilding,
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
            let page: BuildingListItem[];
            do {
                page = await listBuildings({ offset: buildings.length, limit });
                buildings.push(...page);
            } while (page.length === limit);
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
    const visible = ref(document.visibilityState === 'visible');
    const enabled = computed(() => subject !== null && active.value && visible.value);
    const options = computed(() => ({
        offset: offset.value,
        limit: MY_BUILDINGS_PAGE_SIZE + 1,
        sort_order: 'desc' as const,
        reconstruction_status: toValue(reconstructionStatus) ?? null,
        search: toValue(search)?.trim() || null,
    }));

    const query = useQuery({
        key: () => ['buildings', subject, 'list', options.value],
        enabled,
        query: () => listBuildings(options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });

    const shouldPoll = computed(
        () =>
            enabled.value &&
            query.data.value?.slice(0, MY_BUILDINGS_PAGE_SIZE).some((building) => {
                const status = building.latest_reconstruction?.status;
                return status === 'preparing' || status === 'scheduled' || status === 'running';
            }) === true,
    );
    let pollingTimer: ReturnType<typeof setInterval> | undefined;

    function stopPolling() {
        clearInterval(pollingTimer);
        pollingTimer = undefined;
    }

    watch(
        shouldPoll,
        (poll) => {
            stopPolling();
            if (poll) {
                pollingTimer = setInterval(() => {
                    // A slow request must finish before another poll can start.
                    if (shouldPoll.value && query.asyncStatus.value !== 'loading') {
                        void query.refetch();
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
        if (enabled.value) void query.refresh();
    });
    onDeactivated(() => {
        active.value = false;
        stopPolling();
    });
    onScopeDispose(() => {
        stopPolling();
        document.removeEventListener('visibilitychange', updateVisibility);
    });

    return query;
}
