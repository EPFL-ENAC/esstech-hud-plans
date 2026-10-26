<template>
    <video-recorder
        :busy="busy || closing"
        :recording-disabled="accepted"
        :error-message="localError || errorMessage"
        @recorded="uploadRecording"
        @discard="openPicker"
    >
        <template #error-actions>
            <q-btn
                v-if="accepted"
                flat
                no-caps
                :loading="busy"
                :label="t(uploadId ? 'reconstructions.fromUpload.openForm' : 'common.retry')"
                @click="retry"
            />
        </template>
    </video-recorder>
    <loading-overlay v-if="busy" :message="t('reconstructions.fromUpload.starting')" />
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import VideoRecorder from 'src/components/VideoRecorder.vue';
import LoadingOverlay from 'src/components/LoadingOverlay.vue';
import { useUploadForReconstruction } from 'src/composables/useUploadForReconstruction';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';

const { t } = useI18n();
const router = useRouter();
const route = useRoute();
const { startUpload, retry, busy, uploadId, errorMessage } = useUploadForReconstruction();
const accepted = ref(false);
const closing = ref(false);
const localError = ref('');

function uploadRecording(recording: RecordedVideo): void {
    if (accepted.value || busy.value || closing.value) return;
    localError.value = '';
    try {
        const file = toCapturedVideo(recording, null).file;
        accepted.value = true;
        startUpload(file);
    } catch (error) {
        localError.value = error instanceof Error ? error.message : t('capture.openFailed');
    }
}

async function openPicker(): Promise<void> {
    if (busy.value || closing.value) return;
    closing.value = true;
    localError.value = '';
    try {
        const failure = await router.replace({
            name: 'reconstruction-upload-picker',
            query: { buildingId: route.query.buildingId },
        });
        if (failure) localError.value = t('reconstructions.fromUpload.pickerNavigationFailed');
    } catch {
        localError.value = t('reconstructions.fromUpload.pickerNavigationFailed');
    } finally {
        closing.value = false;
    }
}
</script>
