<template>
    <q-form class="q-gutter-y-md" @submit="submit">
        <slot name="before" />

        <q-file
            v-model="videoFile"
            outlined
            accept="video/*"
            label="Video file"
            clearable
            :disable="loading"
        >
            <template #prepend><q-icon name="movie" /></template>
        </q-file>
        <q-btn
            outline
            no-caps
            icon="video_library"
            :label="t('uploads.picker.action')"
            :disable="loading"
            @click="pickerOpen = true"
        />
        <uploaded-video-picker-dialog v-model="pickerOpen" @select="selectUpload" />
        <uploaded-video-details
            v-if="selectedUpload"
            :upload="selectedUpload"
            :disable="loading"
            @clear="selectedUpload = null"
        />

        <reconstruction-settings v-model="settings" />

        <q-btn
            color="primary"
            icon="upload"
            :label="submitLabel"
            type="submit"
            :disable="!canSubmit || loading"
            :loading="loading"
        />
    </q-form>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import UploadedVideoDetails from 'src/components/UploadedVideoDetails.vue';
import UploadedVideoPickerDialog from 'src/components/UploadedVideoPickerDialog.vue';
import type { ReconstructionSubmission } from 'src/lib/buildings';
import type { UserUpload } from 'src/lib/uploads';
import {
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';

withDefaults(defineProps<{ loading?: boolean; submitLabel?: string }>(), {
    loading: false,
    submitLabel: 'Submit reconstruction',
});

const emit = defineEmits<{ submit: [submission: ReconstructionSubmission] }>();
const { t } = useI18n();
const videoFile = ref<File | null>(null);
const selectedUpload = ref<UserUpload | null>(null);
const pickerOpen = ref(false);
const settings = ref(makeDefaultReconstructionSettings());
const canSubmit = computed(
    () =>
        (videoFile.value !== null || selectedUpload.value !== null) &&
        isValidReconstructionSettings(settings.value),
);

watch(
    videoFile,
    (file) => {
        if (file) selectedUpload.value = null;
    },
    { flush: 'sync' },
);

function selectUpload(upload: UserUpload): void {
    videoFile.value = null;
    selectedUpload.value = upload;
}

function submit(): void {
    if (!canSubmit.value) return;
    const submissionSettings = toSplatGenerationSettings(settings.value);
    if (selectedUpload.value) {
        emit('submit', { uploadId: selectedUpload.value.id, settings: submissionSettings });
    } else if (videoFile.value) {
        emit('submit', { video: videoFile.value, settings: submissionSettings });
    }
}
</script>
