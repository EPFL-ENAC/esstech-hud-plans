<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header title="New Capture" />

        <video-picker v-model="videoFile" class="q-mb-md" @metadata="videoMetadata = $event" />

        <q-select
            v-model="selectedBuilding"
            outlined
            :options="buildingOptions"
            :loading="isLoadingBuildings"
            label="Building"
            class="q-mb-md"
        >
            <template #option="scope">
                <q-item v-bind="scope.itemProps">
                    <q-item-section>
                        <q-item-label>{{ scope.opt.label }}</q-item-label>
                    </q-item-section>
                </q-item>
                <q-separator
                    v-if="scope.index === 0 && buildingOptions.length > 1"
                    class="q-virtual-scroll--with-prev"
                />
            </template>
        </q-select>

        <q-banner v-if="buildingsState.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            Could not load your buildings.
            <template #action>
                <q-btn
                    flat
                    label="Retry"
                    :disable="isLoadingBuildings"
                    @click="refetchBuildings()"
                />
            </template>
        </q-banner>

        <q-input
            v-if="selectedBuilding.value === null"
            v-model="name"
            outlined
            label="Building name"
            class="q-mb-md"
        />

        <q-input
            v-model="description"
            type="textarea"
            outlined
            label="Description"
            class="q-mb-md"
        />

        <q-select
            v-model="preset"
            outlined
            :options="presetOptions"
            label="Preset"
            class="q-mb-xl"
        />

        <section v-if="preset === 'advanced'" class="q-mb-xl" aria-label="Advanced settings">
            <reconstruction-settings v-model="advancedSettings" />
            <p v-if="!hasValidSettings" class="text-negative q-mt-md" role="alert">
                Check the settings: counts must be positive whole numbers, SH degree must be between
                0 and 3, and sharpness ratio must be between 0 and 1. Stop growth may be zero;
                distance threshold cannot be negative.
            </p>
        </section>

        <q-btn
            label="Start Processing (10-60min)"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            :disable="!videoFile || !videoMetadata || !hasValidSettings"
            @click="startProcessing"
        />
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useBuildingsStore } from 'src/stores/buildings';
import PageHeader from 'src/components/PageHeader.vue';
import VideoPicker from 'src/components/VideoPicker.vue';
import type { VideoMetadata } from 'src/components/VideoPicker.types';
import { useAllBuildingsQuery } from 'src/queries/buildings';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import {
    type ReconstructionPreset,
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';

interface SelectOption {
    label: string;
    value: string | null;
}

const router = useRouter();
const route = useRoute();
const $q = useQuasar();
const buildingsStore = useBuildingsStore();

const createNewOption: SelectOption = { label: 'Create new', value: null };
const selectedBuildingId = ref<string | null>(null);
watch(
    () => route.query.buildingId,
    (buildingId) => {
        selectedBuildingId.value = typeof buildingId === 'string' ? buildingId : null;
    },
    { immediate: true },
);
const {
    data: buildings,
    state: buildingsState,
    asyncStatus: buildingsAsyncStatus,
    refetch: refetchBuildings,
} = useAllBuildingsQuery();
const isLoadingBuildings = computed(() => buildingsAsyncStatus.value === 'loading');
const buildingOptions = computed<SelectOption[]>(() => [
    createNewOption,
    ...(buildings.value ?? []).map((building) => ({
        label: building.name.trim() || 'Untitled building',
        value: building.id,
    })),
]);
const selectedBuilding = computed<SelectOption>({
    get: () =>
        buildingOptions.value.find((option) => option.value === selectedBuildingId.value) ??
        createNewOption,
    set: (option) => {
        selectedBuildingId.value = option.value;
    },
});

const name = ref('Building 1');
const description = ref('');
const preset = ref<ReconstructionPreset>('indoors');
const presetOptions: ReconstructionPreset[] = ['indoors', 'outdoors', 'advanced'];
const advancedSettings = ref(makeDefaultReconstructionSettings());
const hasValidSettings = computed(
    () => preset.value !== 'advanced' || isValidReconstructionSettings(advancedSettings.value),
);
const videoFile = ref<File | null>(null);
const videoMetadata = ref<VideoMetadata | null>(null);

function startProcessing(): void {
    if (!videoFile.value || !videoMetadata.value || !hasValidSettings.value) return;

    const id = buildingsStore.startProcessing({
        name: selectedBuilding.value.value === null ? name.value : selectedBuilding.value.label,
        description: description.value,
        environment: preset.value === 'advanced' ? null : preset.value,
        reconstructionSettings: toSplatGenerationSettings(
            preset.value === 'advanced'
                ? advancedSettings.value
                : makeDefaultReconstructionSettings(),
        ),
        ...videoMetadata.value,
    });

    $q.notify({
        type: 'positive',
        message: 'Capture added to simulated processing.',
        position: 'top',
    });
    void router.push(`/capture/processing/${id}`);
}
</script>
