<template>
    <section aria-labelledby="my-buildings-title" :aria-busy="isLoading">
        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mx-md q-mb-md" role="alert">
            {{ data ? 'Could not refresh your buildings.' : 'Could not load your buildings.' }}
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <q-list v-if="state.status === 'pending'" separator class="my-buildings-list">
            <q-item v-for="index in 3" :key="index" aria-hidden="true">
                <q-item-section avatar>
                    <q-skeleton width="72px" height="72px" square />
                </q-item-section>
                <q-item-section>
                    <q-skeleton type="text" width="60%" />
                    <q-skeleton type="text" width="40%" />
                </q-item-section>
            </q-item>
        </q-list>

        <template v-else-if="data">
            <div v-if="isLoading" class="q-px-md q-pb-sm text-grey-7" role="status">
                <q-spinner color="primary" class="q-mr-sm" />
                Refreshing buildings…
            </div>
            <q-list v-if="buildings.length" separator class="my-buildings-list">
                <q-item
                    v-for="building in buildings"
                    :key="building.id"
                    clickable
                    :to="`/building/${building.id}`"
                >
                    <q-item-section avatar>
                        <q-avatar
                            square
                            size="72px"
                            color="white"
                            text-color="primary"
                            class="avatar-icon"
                        >
                            <floor-plan-thumb />
                        </q-avatar>
                    </q-item-section>
                    <q-item-section>
                        <q-item-label class="building-name text-subtitle1 text-weight-medium">
                            {{ building.name.trim() || 'Untitled building' }}
                        </q-item-label>
                        <q-item-label caption>
                            Created {{ formatCreatedAt(building.created_at) }}
                        </q-item-label>
                        <q-item-label>
                            <reconstruction-status-chip
                                :reconstruction="building.latest_reconstruction"
                            />
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-list>
            <p v-else class="q-px-md text-grey-7" role="status">
                {{ emptyMessage }}
            </p>
        </template>

        <nav
            v-if="(data && data.length > 0) || offset > 0"
            aria-label="Building list pagination"
            class="row justify-center q-pa-md"
        >
            <q-pagination
                v-model="page"
                :max="page + Number(hasNext)"
                :max-pages="5"
                :boundary-numbers="false"
                :ellipses="false"
                direction-links
                color="primary"
                :disable="isLoading"
            />
        </nav>
    </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import FloorPlanThumb from 'src/components/FloorPlanThumb.vue';
import ReconstructionStatusChip from 'src/components/ReconstructionStatusChip.vue';
import type { ReconstructionStatusFilter } from 'src/lib/buildings';
import { MY_BUILDINGS_PAGE_SIZE, useMyBuildingsQuery } from 'src/queries/buildings';

const props = defineProps<{
    search?: string | null;
    reconstructionStatus?: ReconstructionStatusFilter | null;
}>();
const normalizedSearch = computed(() => props.search?.trim() || null);
const offset = ref(0);
watch(
    [normalizedSearch, () => props.reconstructionStatus],
    () => {
        offset.value = 0;
    },
    { flush: 'sync' },
);
const {
    data,
    state,
    refetch,
    isForegroundLoading: isLoading,
} = useMyBuildingsQuery(offset, () => props.reconstructionStatus, normalizedSearch);
const emptyMessage = computed(() => {
    if (offset.value > 0) return 'No buildings on this page.';
    return normalizedSearch.value ? 'No buildings match your search.' : 'No buildings yet.';
});
const buildings = computed(() => data.value?.slice(0, MY_BUILDINGS_PAGE_SIZE) ?? []);
const hasNext = computed(() => (data.value?.length ?? 0) > MY_BUILDINGS_PAGE_SIZE);
const page = computed({
    get: () => offset.value / MY_BUILDINGS_PAGE_SIZE + 1,
    set: (value: number) => {
        offset.value = (value - 1) * MY_BUILDINGS_PAGE_SIZE;
    },
});
const dateFormatter = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
});

function formatCreatedAt(value: string): string {
    return dateFormatter.format(new Date(value));
}
</script>

<style scoped>
.my-buildings-list {
    border-top: 1px solid rgba(0, 0, 0, 0.12);
    border-bottom: 1px solid rgba(0, 0, 0, 0.12);
}

.building-name {
    overflow-wrap: anywhere;
}
</style>
