<template>
    <div class="reconstruction-form">
        <section class="q-mb-xl">
            <h2 class="text-h6 text-weight-bold">{{ t('capture.destinationBuilding') }}</h2>
            <building-picker
                v-model="buildingSelection"
                :disable="disabled || locked"
                class="q-mb-md"
                @valid="hasValidBuilding = $event"
            />
        </section>

        <section class="q-mb-xl">
            <h2 class="text-h6 text-weight-bold">{{ t('capture.reconstructionSettings') }}</h2>
            <q-select
                v-model="preset"
                outlined
                :options="presetOptions"
                emit-value
                map-options
                :label="t('capture.preset')"
                :disable="disabled || locked"
                class="q-mb-xl"
            />
            <section
                v-if="preset === 'advanced'"
                class="q-mb-xl"
                :aria-label="t('capture.advancedSettings')"
            >
                <reconstruction-settings v-model="advancedSettings" />
                <p v-if="!hasValidSettings" class="text-negative q-mt-md" role="alert">
                    {{ t('capture.invalidSettings') }}
                </p>
            </section>
            <q-banner v-if="submissionError" class="bg-red-1 text-negative q-mb-md" role="alert">
                {{ submissionError }}
                <template v-if="destinationBuildingId" #action>
                    <q-btn
                        flat
                        no-caps
                        :label="t('buildings.view')"
                        @click="openBuilding(destinationBuildingId)"
                    />
                </template>
            </q-banner>
        </section>

        <video-upload-progress
            v-if="submissionState.phase !== 'idle'"
            :state="submissionState"
            class="q-mb-md"
        />

        <q-btn
            :label="t('capture.startProcessing')"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            :loading="submitting"
            :disable="!canSubmit"
            @click="startProcessing"
        />
    </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useI18n } from 'vue-i18n';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import VideoUploadProgress from 'src/components/VideoUploadProgress.vue';
import type { BuildingSelection, ReconstructionSource } from 'src/lib/buildings';
import {
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';
import { useSubmitReconstructionMutation } from 'src/mutations/reconstructions';
import { useUiStore } from 'src/stores/ui';

const props = defineProps<{
    source: ReconstructionSource | null;
    disabled?: boolean;
}>();
const buildingSelection = defineModel<BuildingSelection>('buildingSelection', { required: true });
const preset = defineModel<ReconstructionPreset>('preset', { required: true });
const advancedSettings = defineModel<ReconstructionSettingsConfig>('advancedSettings', {
    required: true,
});
const { t } = useI18n();
const router = useRouter();
const ui = useUiStore();
const $q = useQuasar();
const {
    mutateAsync: submitReconstruction,
    isLoading: submitting,
    submissionState,
    destinationBuildingId,
    errorMessage: mutationError,
} = useSubmitReconstructionMutation();
const navigationError = ref('');
const submissionError = computed(() => navigationError.value || mutationError.value);
const hasValidBuilding = ref(false);
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const hasValidSettings = computed(
    () => preset.value !== 'advanced' || isValidReconstructionSettings(advancedSettings.value),
);
const locked = computed(() => submitting.value || destinationBuildingId.value !== null);
const canSubmit = computed(
    () =>
        !props.disabled &&
        !locked.value &&
        props.source !== null &&
        hasValidSettings.value &&
        hasValidBuilding.value,
);

async function startProcessing(): Promise<void> {
    if (!canSubmit.value || !props.source) return;

    const settings = toSplatGenerationSettings(
        preset.value === 'advanced'
            ? advancedSettings.value
            : makeDefaultReconstructionSettings(preset.value),
    );
    navigationError.value = '';
    // Colada exposes submission errors through mutationError, including retained IDs.
    await submitReconstruction({ ...props.source, settings, ...buildingSelection.value }).catch(
        () => undefined,
    );

    if (destinationBuildingId.value === null) return;
    $q.notify({
        type: mutationError.value ? 'negative' : 'positive',
        message: mutationError.value || t('reconstructions.submitted'),
        position: 'top',
    });
    await openBuilding(destinationBuildingId.value);
}

async function openBuilding(buildingId: string): Promise<void> {
    ui.setBackground('library');
    try {
        const failure = await router.push(`/building/${encodeURIComponent(buildingId)}`);
        if (failure) {
            navigationError.value = t('buildings.savedNavigationFailed');
        }
    } catch {
        navigationError.value = t('buildings.savedNavigationFailed');
    }
}
defineExpose({ locked });
</script>
