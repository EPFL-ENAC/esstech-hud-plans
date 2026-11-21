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
            <reconstruction-preset-settings
                v-model:preset="preset"
                v-model:advanced-settings="advancedSettings"
                :disable-preset="disabled || locked"
                @valid="hasValidSettings = $event"
            />
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

        <div v-if="submitting" class="q-mb-md" role="status" aria-live="polite">
            <q-linear-progress indeterminate rounded color="primary" />
            <div class="text-caption text-grey-7 q-mt-xs">
                {{ t('capture.submittingReconstruction') }}
            </div>
        </div>

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
import { useQuasar } from 'quasar';
import { useI18n } from 'vue-i18n';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import ReconstructionPresetSettings from 'src/components/ReconstructionPresetSettings.vue';
import { useRouteNavigation } from 'src/composables/useRouteNavigation';
import type { BuildingSelection } from 'src/lib/buildings';
import {
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';
import { useSubmitReconstructionMutation } from 'src/mutations/reconstructions';
import { useUiStore } from 'src/stores/ui';

const props = defineProps<{
    uploadId: string;
    disabled?: boolean;
}>();
const buildingSelection = defineModel<BuildingSelection>('buildingSelection', { required: true });
const preset = defineModel<ReconstructionPreset>('preset', { required: true });
const advancedSettings = defineModel<ReconstructionSettingsConfig>('advancedSettings', {
    required: true,
});
const { t } = useI18n();
const ui = useUiStore();
const $q = useQuasar();
const {
    mutateAsync: submitReconstruction,
    isLoading: submitting,
    destinationBuildingId,
    errorMessage: mutationError,
} = useSubmitReconstructionMutation();
const { navigationFailed, clearNavigationFailure, push } = useRouteNavigation();
const submissionError = computed(() =>
    navigationFailed.value ? t('buildings.savedNavigationFailed') : mutationError.value,
);
const hasValidBuilding = ref(false);
const hasValidSettings = ref(false);
const locked = computed(() => submitting.value || destinationBuildingId.value !== null);
const canSubmit = computed(
    () => !props.disabled && !locked.value && hasValidSettings.value && hasValidBuilding.value,
);

async function startProcessing(): Promise<void> {
    if (!canSubmit.value) return;

    const settings = toSplatGenerationSettings(
        preset.value === 'advanced'
            ? advancedSettings.value
            : makeDefaultReconstructionSettings(preset.value),
    );
    clearNavigationFailure();
    // Colada exposes submission errors through mutationError, including retained IDs.
    await submitReconstruction({
        uploadId: props.uploadId,
        settings,
        ...buildingSelection.value,
    }).catch(() => undefined);

    if (destinationBuildingId.value === null) return;
    $q.notify({
        type: mutationError.value ? 'negative' : 'positive',
        message: mutationError.value || t('reconstructions.submitted'),
        position: 'top',
    });
    await openBuilding(destinationBuildingId.value);
}

function openBuilding(buildingId: string): Promise<void> {
    ui.setBackground('library');
    return push(`/building/${encodeURIComponent(buildingId)}`);
}
defineExpose({ locked });
</script>
