<template>
    <video-recorder
        :busy="busy"
        :error-message="handoffError"
        @recorded="acceptRecording"
        @discard="discardCapture"
    />
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import VideoRecorder from 'src/components/VideoRecorder.vue';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useCaptureStore } from 'src/stores/capture';

const { t } = useI18n();
const router = useRouter();
const captureStore = useCaptureStore();
// Preserve whether the recorder was opened from a form for history navigation.
const returnTo = captureStore.returnTo;
const draftReturnTo = captureStore.ensureDraft().returnTo;
const busy = ref(false);
const handoffError = ref('');
let disposed = false;

async function acceptRecording(recording: RecordedVideo): Promise<void> {
    if (busy.value || disposed) return;

    busy.value = true;
    handoffError.value = '';
    try {
        captureStore.setDraftVideo(toCapturedVideo(recording, null));
        const failure = returnTo ? await router.replace(returnTo) : await router.push('/capture');
        if (failure && !disposed) handoffError.value = t('capture.handoffFailed');
    } catch (error) {
        if (!disposed) {
            handoffError.value = error instanceof Error ? error.message : t('capture.openFailed');
        }
    } finally {
        busy.value = false;
    }
}

async function discardCapture(): Promise<void> {
    // An in-progress recorder is discarded by the viewfinder's unmount
    // cleanup when the page unloads.
    if (returnTo) {
        try {
            const failure = await router.replace(returnTo);
            if (failure) handoffError.value = t('capture.openFailed');
        } catch {
            handoffError.value = t('capture.openFailed');
        }
    } else if (router.options.history.state?.back) {
        router.back();
    } else {
        await router.push('/capture');
    }
}

onBeforeUnmount(() => {
    disposed = true;
    if (router.currentRoute.value.fullPath !== draftReturnTo) {
        captureStore.clearDraft();
    }
});
</script>
