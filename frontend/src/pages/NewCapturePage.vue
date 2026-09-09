<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('capture.newCapture')" />

        <video-picker
            v-model="videoFile"
            :fallback-duration-seconds="fallbackDurationSeconds"
            class="q-mb-lg"
            @metadata="videoMetadata = $event"
        />

        <building-picker
            v-model="buildingSelection"
            :disable="submitting || destinationBuildingId !== null"
            class="q-mb-md"
            @valid="hasValidBuilding = $event"
        />

        <q-select
            v-model="preset"
            outlined
            :options="presetOptions"
            emit-value
            map-options
            :label="t('capture.preset')"
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
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useSubmitReconstructionMutation } from 'src/mutations/reconstructions';
import { useCaptureStore } from 'src/stores/capture';
import PageHeader from 'src/components/PageHeader.vue';
import VideoPicker from 'src/components/VideoPicker.vue';
import type { VideoMetadata } from 'src/components/VideoPicker.types';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import type { BuildingSelection } from 'src/lib/buildings';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import {
    type ReconstructionPreset,
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const router = useRouter();
const route = useRoute();
const $q = useQuasar();
const {
    mutateAsync: submitReconstruction,
    isLoading: submitting,
    destinationBuildingId,
    errorMessage: mutationError,
} = useSubmitReconstructionMutation();
const navigationError = ref('');
const submissionError = computed(() => navigationError.value || mutationError.value);

const capturedVideo = shallowRef(useCaptureStore().takeVideo());
const buildingSelection = ref<BuildingSelection>({ buildingId: '' });
const hasValidBuilding = ref(false);
watch(
    () => route.query.buildingId,
    (buildingId) => {
        buildingSelection.value =
            buildingId === undefined
                ? {
                      buildingId: null,
                      building: {
                          name: t('buildings.defaultName', { number: 1 }),
                          latitude: capturedVideo.value?.location?.latitude ?? null,
                          longitude: capturedVideo.value?.location?.longitude ?? null,
                      },
                  }
                : { buildingId: typeof buildingId === 'string' ? buildingId : '' };
    },
    { immediate: true },
);

const preset = ref<ReconstructionPreset>('indoors');
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const advancedSettings = ref(makeDefaultReconstructionSettings());
const hasValidSettings = computed(
    () => preset.value !== 'advanced' || isValidReconstructionSettings(advancedSettings.value),
);
const videoFile = ref<File | null>(capturedVideo.value?.file ?? null);
const fallbackDurationSeconds = computed(() =>
    capturedVideo.value && videoFile.value === capturedVideo.value.file
        ? capturedVideo.value.durationSeconds
        : undefined,
);
watch(
    videoFile,
    (file) => {
        if (file !== capturedVideo.value?.file) capturedVideo.value = null;
    },
    { flush: 'sync' },
);
const videoMetadata = ref<VideoMetadata | null>(null);
const canSubmit = computed(
    () =>
        !submitting.value &&
        destinationBuildingId.value === null &&
        videoFile.value !== null &&
        videoMetadata.value !== null &&
        hasValidSettings.value &&
        hasValidBuilding.value,
);

async function startProcessing(): Promise<void> {
    if (!canSubmit.value || !videoFile.value) return;

    const submission = {
        video: videoFile.value,
        settings: toSplatGenerationSettings(
            preset.value === 'advanced'
                ? advancedSettings.value
                : makeDefaultReconstructionSettings(),
        ),
    };
    navigationError.value = '';
    // Colada exposes submission errors through mutationError, including retained IDs.
    await submitReconstruction({ ...submission, ...buildingSelection.value }).catch(
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
    try {
        const failure = await router.push(`/building/${encodeURIComponent(buildingId)}`);
        if (failure) {
            navigationError.value = t('buildings.savedNavigationFailed');
        }
    } catch {
        navigationError.value = t('buildings.savedNavigationFailed');
    }
}
</script>
