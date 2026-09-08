<template>
    <section aria-labelledby="reconstructions-title" :aria-busy="isLoading" class="q-mb-lg">
        <h2 id="reconstructions-title" class="text-h6 text-weight-bold q-mb-md">Reconstructions</h2>

        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ data ? 'Could not refresh reconstructions.' : 'Could not load reconstructions.' }}
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>
        <div v-if="state.status === 'pending'" role="status" aria-label="Loading reconstructions">
            <q-skeleton v-for="index in 3" :key="index" height="72px" class="q-mb-sm" />
        </div>
        <template v-else-if="data">
            <div v-if="isLoading" class="text-grey-7 q-mb-sm" role="status">
                <q-spinner color="primary" class="q-mr-sm" />
                Refreshing reconstructions…
            </div>
            <q-list v-if="reconstructions.length" bordered separator class="rounded-borders">
                <q-expansion-item
                    v-for="reconstruction in reconstructions"
                    :key="reconstruction.id"
                    :model-value="expandedId === reconstruction.id"
                    expand-separator
                    @update:model-value="(open) => setExpanded(reconstruction.id, open)"
                >
                    <template #header>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium">
                                Reconstruction {{ reconstruction.id.slice(0, 8) }}
                            </q-item-label>
                            <q-item-label caption>
                                {{ dateFormatter.format(new Date(reconstruction.created_at)) }}
                            </q-item-label>
                            <q-item-label>
                                <reconstruction-status-chip
                                    :reconstruction="reconstruction"
                                    tooltip="Reconstruction attempt"
                                />
                            </q-item-label>
                        </q-item-section>
                    </template>
                    <div class="q-pa-md">
                        <div class="row wrap q-gutter-sm q-mb-md">
                            <q-btn
                                outline
                                no-caps
                                color="primary"
                                icon="map"
                                label="2D Plan"
                                :to="`/building/${buildingId}/plan/2d`"
                            />
                            <span>
                                <q-btn
                                    outline
                                    no-caps
                                    color="primary"
                                    icon="view_in_ar"
                                    label="3D Plan"
                                    :disable="!hasSplat(reconstruction)"
                                    :to="{
                                        name: 'reconstruction-3d-plan',
                                        params: { buildingId, reconstructionId: reconstruction.id },
                                    }"
                                />
                                <q-tooltip v-if="!hasSplat(reconstruction)">
                                    The 3D plan is not available for this reconstruction.
                                </q-tooltip>
                            </span>
                        </div>
                        <reconstruction-video
                            :building-id="buildingId"
                            :reconstruction-id="reconstruction.id"
                            :active="expandedId === reconstruction.id"
                        />
                    </div>
                </q-expansion-item>
            </q-list>
            <p v-else class="text-grey-7" role="status">
                {{ offset === 0 ? 'No reconstructions yet.' : 'No reconstructions on this page.' }}
            </p>
        </template>
        <nav
            v-if="data || offset > 0"
            aria-label="Reconstruction pagination"
            class="row justify-center q-pt-md"
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
import { computed, ref, toRef, watch } from 'vue';
import ReconstructionStatusChip from 'src/components/ReconstructionStatusChip.vue';
import ReconstructionVideo from 'src/components/ReconstructionVideo.vue';
import type { Reconstruction } from 'src/lib/buildings';
import { RECONSTRUCTIONS_PAGE_SIZE, useReconstructionsQuery } from 'src/queries/reconstructions';

const props = defineProps<{ buildingId: string }>();
const offset = ref(0);
const expandedId = ref<string | null>(null);
const { data, state, asyncStatus, refetch } = useReconstructionsQuery(
    toRef(props, 'buildingId'),
    offset,
);
const isLoading = computed(() => asyncStatus.value === 'loading');
const reconstructions = computed(() => data.value?.slice(0, RECONSTRUCTIONS_PAGE_SIZE) ?? []);
const hasNext = computed(() => (data.value?.length ?? 0) > RECONSTRUCTIONS_PAGE_SIZE);
const page = computed({
    get: () => offset.value / RECONSTRUCTIONS_PAGE_SIZE + 1,
    set: (value: number) => {
        expandedId.value = null;
        offset.value = (value - 1) * RECONSTRUCTIONS_PAGE_SIZE;
    },
});
const dateFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
});

function setExpanded(id: string, open: boolean) {
    if (open) expandedId.value = id;
    else if (expandedId.value === id) expandedId.value = null;
}
function hasSplat(reconstruction: Reconstruction): boolean {
    return reconstruction.status === 'completed' && reconstruction.splat_path !== null;
}
watch(reconstructions, (rows) => {
    if (!rows.some(({ id }) => id === expandedId.value)) expandedId.value = null;
});
</script>
