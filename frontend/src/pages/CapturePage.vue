<template>
    <q-page class="capture-page">
        <page-header :back="false" :title="t('capture.newCapture')" />

        <section class="q-mb-xl">
            <h2 class="text-h6 text-weight-bold">{{ t('capture.sourceVideo') }}</h2>

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
                <span class="text-grey text-italic">{{ t('common.or') }}</span>
                <file-picker-button
                    v-model="videoFile"
                    accept="video/*"
                    :disable="sourceSelectionDisabled"
                />
                <span class="text-grey text-italic">{{ t('common.or') }}</span>
                <q-btn
                    :label="t('uploads.picker.action')"
                    :disable="sourceSelectionDisabled"
                    icon="video_library"
                    color="primary"
                    outline
                    no-caps
                    @click="pickerOpen = true"
                />
            </div>
            <uploaded-video-picker-dialog v-model="pickerOpen" @select="selectUpload" />
            <uploaded-video-details
                v-if="selectedUpload"
                :upload="selectedUpload"
                :disable="sourceSelectionDisabled"
                class="q-mb-md"
                @clear="selectedUpload = null"
            />
            <video-preview
                :file="videoFile"
                :fallback-duration-seconds="fallbackDurationSeconds"
                :disable="sourceSelectionDisabled"
                class="capture-video-preview"
                @metadata="videoMetadata = $event"
                @clear="videoFile = null"
            />
        </section>

        <q-banner v-if="navigationError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ navigationError }}
        </q-banner>
        <reconstruction-form
            ref="form"
            v-model:building-selection="buildingSelection"
            v-model:preset="preset"
            v-model:advanced-settings="advancedSettings"
            :source="source"
            :disabled="openingRecorder"
        />
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { computed, ref, shallowRef, useTemplateRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { makeEmptyCaptureDraft, useCaptureStore } from 'src/stores/capture';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import VideoPreview from 'src/components/VideoPreview.vue';
import UploadedVideoDetails from 'src/components/UploadedVideoDetails.vue';
import UploadedVideoPickerDialog from 'src/components/UploadedVideoPickerDialog.vue';
import type { VideoMetadata } from 'src/components/VideoPreview.types';
import type { BuildingSelection, ReconstructionSource } from 'src/lib/buildings';
import type { UserUpload } from 'src/lib/uploads';
import type { ReconstructionPreset } from 'src/lib/reconstruction-settings';
import ReconstructionForm from 'src/components/ReconstructionForm.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const router = useRouter();
const route = useRoute();
const navigationError = ref('');
const form = useTemplateRef<InstanceType<typeof ReconstructionForm>>('form');

const captureStore = useCaptureStore();
const savedDraft = captureStore.takeDraft();
const hasMatchingDraft = savedDraft?.returnTo === route.fullPath;
const draft = hasMatchingDraft ? savedDraft : makeEmptyCaptureDraft(route.fullPath);
const capturedVideo = shallowRef(draft.capturedVideo);

function defaultBuildingSelection(): BuildingSelection {
    const buildingId = route.query.buildingId;
    if (buildingId !== undefined) {
        return { buildingId: typeof buildingId === 'string' ? buildingId : '' };
    }
    const selection = makeEmptyCaptureDraft().buildingSelection;
    if (selection.buildingId === null) {
        selection.building.latitude = capturedVideo.value?.location?.latitude ?? null;
        selection.building.longitude = capturedVideo.value?.location?.longitude ?? null;
    }
    return selection;
}

const buildingSelection = ref<BuildingSelection>(
    hasMatchingDraft ? draft.buildingSelection : defaultBuildingSelection(),
);
watch(
    () => route.query.buildingId,
    () => {
        if (route.path === '/capture') buildingSelection.value = defaultBuildingSelection();
    },
);

const preset = ref<ReconstructionPreset>(draft.preset);
const advancedSettings = ref(draft.advancedSettings);
const videoFile = ref<File | null>(draft.videoFile);
const selectedUpload = ref<UserUpload | null>(draft.selectedUpload);
const pickerOpen = ref(false);
const fallbackDurationSeconds = computed(() =>
    capturedVideo.value && videoFile.value === capturedVideo.value.file
        ? capturedVideo.value.durationSeconds
        : undefined,
);
watch(
    videoFile,
    (file) => {
        if (file !== capturedVideo.value?.file) capturedVideo.value = null;
        if (file) selectedUpload.value = null;
    },
    { flush: 'sync' },
);
const videoMetadata = ref<VideoMetadata | null>(null);
const openingRecorder = ref(false);
const sourceSelectionDisabled = computed(
    () => openingRecorder.value || form.value?.locked === true,
);
const source = computed<ReconstructionSource | null>(() => {
    if (selectedUpload.value) return { uploadId: selectedUpload.value.id };
    if (videoFile.value && videoMetadata.value) return { video: videoFile.value };
    return null;
});

function selectUpload(upload: UserUpload): void {
    if (sourceSelectionDisabled.value) return;
    videoFile.value = null;
    selectedUpload.value = upload;
}

async function openRecorder(): Promise<void> {
    if (sourceSelectionDisabled.value) return;
    openingRecorder.value = true;
    navigationError.value = '';
    captureStore.saveDraft({
        returnTo: route.fullPath,
        videoFile: videoFile.value,
        selectedUpload: selectedUpload.value,
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
</script>

<style scoped>
.capture-page {
    padding: 64px 16px 48px;
    background: #fff;
    color: var(--q-dark);
}

.video-source-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
}

.video-source-actions > * {
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}

.video-source-actions > .q-btn,
.video-source-actions > :deep(.file-picker-button) {
    flex: 1 1 160px;
}

.capture-video-preview {
    margin-bottom: 24px;
}

@media (max-width: 599px) {
    .video-source-actions > span {
        display: none;
    }

    .video-source-actions > .q-btn,
    .video-source-actions > :deep(.file-picker-button) {
        flex-basis: 100%;
    }
}
</style>
