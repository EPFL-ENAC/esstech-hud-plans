<template>
    <q-page class="q-pa-md">
        <div class="page-content q-gutter-y-md">
            <div class="row items-center justify-between q-gutter-sm">
                <div class="row items-center q-gutter-sm">
                    <q-btn flat round icon="arrow_back" aria-label="Back" to="/buildings" />
                    <div>
                        <h1 class="text-h5 q-my-none">
                            {{ building?.name || 'Unnamed building' }}
                        </h1>
                        <div class="text-caption text-grey-7">{{ coordinates }}</div>
                    </div>
                </div>
                <q-btn
                    outline
                    color="primary"
                    icon="refresh"
                    label="Refresh"
                    :loading="loading"
                    @click="load"
                />
            </div>

            <q-banner v-if="errorMessage" rounded class="bg-red-1 text-negative">
                <div class="row items-center justify-between">
                    <span>{{ errorMessage }}</span>
                    <q-btn flat dense color="negative" label="Retry" @click="load" />
                </div>
            </q-banner>

            <div v-if="loading && !building" class="row justify-center q-pa-xl">
                <q-spinner color="primary" size="3em" />
            </div>

            <template v-else-if="building">
                <q-card flat bordered>
                    <q-card-section class="row q-col-gutter-md">
                        <div class="col-12 col-sm-6">
                            <div class="text-caption text-grey-7">Building ID</div>
                            <div class="selectable-text">{{ building.id }}</div>
                        </div>
                        <div class="col-12 col-sm-6">
                            <div class="text-caption text-grey-7">Coordinates</div>
                            <div>{{ coordinates }}</div>
                        </div>
                    </q-card-section>
                </q-card>

                <div class="text-h6">Reconstructions</div>
                <q-card v-if="reconstructions.length === 0" flat bordered>
                    <q-card-section class="text-grey-7">No reconstructions yet.</q-card-section>
                </q-card>

                <q-card v-for="item in reconstructions" :key="item.id" flat bordered>
                    <q-card-section class="row items-start justify-between q-gutter-sm">
                        <div>
                            <div class="text-subtitle1 text-weight-medium selectable-text">
                                {{ item.id }}
                            </div>
                            <div class="text-caption text-grey-7">
                                Created {{ formatDate(item.created_at) }} · updated
                                {{ formatDate(item.updated_at) }}
                            </div>
                        </div>
                        <q-chip dense :color="statusColor(item.status)" text-color="white">
                            {{ item.status }}
                        </q-chip>
                    </q-card-section>
                    <q-card-section class="q-pt-none q-gutter-y-sm">
                        <div class="row items-center q-gutter-sm">
                            <q-linear-progress
                                class="col"
                                rounded
                                size="12px"
                                color="primary"
                                :value="item.progress"
                            />
                            <span class="text-caption">{{ Math.round(item.progress * 100) }}%</span>
                        </div>
                        <q-banner v-if="item.error_message" dense class="bg-red-1 text-negative">
                            {{ item.error_message }}
                        </q-banner>
                        <ReconstructionVideo
                            v-if="item.input_video_path"
                            :building-id="item.building_id"
                            :reconstruction-id="item.id"
                        />
                        <div v-else class="text-grey-7">Input video is not available yet.</div>
                        <ReconstructionSplat
                            v-if="item.status === 'completed'"
                            :building-id="item.building_id"
                            :reconstruction-id="item.id"
                        />
                        <div>
                            <span class="text-caption text-grey-7">Prefect workflow: </span>
                            <span class="text-caption selectable-text">{{
                                item.prefect_workflow_id || 'Not scheduled'
                            }}</span>
                        </div>
                        <q-list v-if="artifactPaths(item).length" dense bordered separator>
                            <q-item v-for="artifact in artifactPaths(item)" :key="artifact.label">
                                <q-item-section>
                                    <q-item-label caption>{{ artifact.label }}</q-item-label>
                                    <q-item-label class="artifact-path selectable-text">{{
                                        artifact.path
                                    }}</q-item-label>
                                </q-item-section>
                            </q-item>
                        </q-list>
                    </q-card-section>
                </q-card>
            </template>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import ReconstructionVideo from 'src/components/ReconstructionVideo.vue';
import ReconstructionSplat from 'src/components/ReconstructionSplat.vue';
import {
    type Building,
    type Reconstruction,
    type ReconstructionStatus,
    getBuilding,
    listReconstructions,
} from 'src/lib/buildings';

const route = useRoute();
const building = ref<Building | null>(null);
const reconstructions = ref<Reconstruction[]>([]);
const loading = ref(false);
const errorMessage = ref('');
const buildingId = computed(() => String(route.params.id));
const coordinates = computed(() => {
    if (building.value?.latitude === null || building.value?.longitude === null) {
        return 'Coordinates not set';
    }
    if (!building.value) return '';
    return `${building.value.latitude.toFixed(6)}, ${building.value.longitude.toFixed(6)}`;
});

async function load(): Promise<void> {
    loading.value = true;
    errorMessage.value = '';
    try {
        [building.value, reconstructions.value] = await Promise.all([
            getBuilding(buildingId.value),
            listReconstructions(buildingId.value),
        ]);
    } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : String(error);
    } finally {
        loading.value = false;
    }
}

function statusColor(status: ReconstructionStatus): string {
    if (status === 'completed') return 'positive';
    if (status === 'failed' || status === 'crashed') return 'negative';
    if (status === 'cancelled') return 'grey-7';
    if (status === 'running') return 'primary';
    return 'orange-8';
}

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' }).format(
        new Date(value),
    );
}

function artifactPaths(item: Reconstruction): { label: string; path: string }[] {
    const values = [
        ['Workspace', item.workspace_directory],
        ['Input video', item.input_video_path],
        ['Raw frames', item.raw_frames_directory],
        ['Selected frames', item.frames_directory],
        ['COLMAP', item.colmap_directory],
        ['Splat', item.splat_path],
    ] as const;
    return values.flatMap(([label, path]) => (path === null ? [] : [{ label, path }]));
}

onMounted(load);
</script>

<style scoped>
.page-content {
    max-width: 900px;
    margin: 0 auto;
}
.selectable-text {
    user-select: text;
    overflow-wrap: anywhere;
}
.artifact-path {
    font-family: monospace;
    white-space: normal;
    overflow-wrap: anywhere;
}
</style>
