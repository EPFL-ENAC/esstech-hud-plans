<template>
    <q-page class="capture-page">
        <page-header :back="false" :title="t('capture.newCapture')" />

        <section class="q-mb-xl">
            <h2 class="text-h5">{{ t('capture.sourceVideo') }}</h2>

            <div class="video-source-actions">
                <q-btn
                    :label="t('capture.video.takeVideo')"
                    :disable="sourceSelectionDisabled"
                    icon="videocam"
                    color="primary"
                    outline
                    no-caps
                    @click="openRecorder"
                />
                <span class="text-gray text-italic">{{ t('common.or') }}</span>
                <file-picker-button
                    v-model="videoFile"
                    accept="video/*"
                    :disable="sourceSelectionDisabled"
                />
            </div>
            <video-preview
                :file="videoFile"
                :fallback-duration-seconds="fallbackDurationSeconds"
                :disable="sourceSelectionDisabled"
                class="capture-video-preview"
                @metadata="videoMetadata = $event"
                @clear="videoFile = null"
            />
        </section>

        <section class="q-mb-xl">
            <h2 class="text-h5">{{ t('capture.destinationBuilding') }}</h2>
            <building-picker
                v-model="buildingSelection"
                :disable="submitting || destinationBuildingId !== null"
                class="q-mb-md"
                @valid="hasValidBuilding = $event"
            />
        </section>

        <section class="q-mb-xl">
            <h2 class="text-h5">{{ t('capture.reconstructionSettings') }}</h2>
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
        </section>

        <video-upload-progress v-if="submitting" class="q-mb-md" />

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
import PageHeader from 'src/components/PageHeader.vue';
import { computed, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useSubmitReconstructionMutation } from 'src/mutations/reconstructions';
import { useCaptureStore } from 'src/stores/capture';
import VideoUploadProgress from 'src/components/VideoUploadProgress.vue';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import VideoPreview from 'src/components/VideoPreview.vue';
import type { VideoMetadata } from 'src/components/VideoPreview.types';
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

const captureStore = useCaptureStore();
// BackgroundPage can also render this form behind a detail drawer.
// Only the capture route should consume a recording or a saved form.
const savedDraft = route.path === '/capture' ? captureStore.takeDraft() : null;
const draft = savedDraft?.returnTo === route.fullPath ? savedDraft : null;
const recordedVideo = route.path === '/capture' ? captureStore.takeVideo() : null;
const capturedVideo = shallowRef(recordedVideo ?? draft?.capturedVideo ?? null);

function defaultBuildingSelection(): BuildingSelection {
    const buildingId = route.query.buildingId;
    return buildingId === undefined
        ? {
              buildingId: null,
              building: {
                  name: t('buildings.defaultName', { number: 1 }),
                  latitude: capturedVideo.value?.location?.latitude ?? null,
                  longitude: capturedVideo.value?.location?.longitude ?? null,
              },
          }
        : { buildingId: typeof buildingId === 'string' ? buildingId : '' };
}

const buildingSelection = ref<BuildingSelection>(
    draft?.buildingSelection ?? defaultBuildingSelection(),
);
const hasValidBuilding = ref(false);
watch(
    () => route.query.buildingId,
    () => {
        if (route.path === '/capture') buildingSelection.value = defaultBuildingSelection();
    },
);

const preset = ref<ReconstructionPreset>(draft?.preset ?? 'indoors');
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const advancedSettings = ref(
    draft?.advancedSettings ?? makeDefaultReconstructionSettings('advanced'),
);
const hasValidSettings = computed(
    () => preset.value !== 'advanced' || isValidReconstructionSettings(advancedSettings.value),
);
const videoFile = ref<File | null>(recordedVideo?.file ?? draft?.videoFile ?? null);
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
const openingRecorder = ref(false);
const sourceSelectionDisabled = computed(
    () => openingRecorder.value || submitting.value || destinationBuildingId.value !== null,
);
const canSubmit = computed(
    () =>
        !sourceSelectionDisabled.value &&
        videoFile.value !== null &&
        videoMetadata.value !== null &&
        hasValidSettings.value &&
        hasValidBuilding.value,
);

async function openRecorder(): Promise<void> {
    if (sourceSelectionDisabled.value) return;
    openingRecorder.value = true;
    navigationError.value = '';
    captureStore.saveDraft({
        returnTo: route.fullPath,
        videoFile: videoFile.value,
        capturedVideo: capturedVideo.value,
        buildingSelection: buildingSelection.value,
        preset: preset.value,
        advancedSettings: advancedSettings.value,
    });
    try {
        const failure = await router.push('/capture/record');
        if (failure) {
            captureStore.clearDraft();
            navigationError.value = t('capture.record.openFailed');
        }
    } catch {
        captureStore.clearDraft();
        navigationError.value = t('capture.record.openFailed');
    } finally {
        openingRecorder.value = false;
    }
}

async function startProcessing(): Promise<void> {
    if (!canSubmit.value || !videoFile.value) return;

    const submission = {
        video: videoFile.value,
        settings: toSplatGenerationSettings(
            preset.value === 'advanced'
                ? advancedSettings.value
                : makeDefaultReconstructionSettings(preset.value),
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

<style scoped>
.capture-page {
    padding: 64px 16px 48px;
    background: #fff;
    color: var(--q-dark);
}

.video-source-actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) max-content minmax(0, 1fr);
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
}

.video-source-actions > * {
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}

.capture-video-preview {
    margin-bottom: 24px;
}
</style>
