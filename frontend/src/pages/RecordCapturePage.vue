<template>
    <video-recorder
        :busy="busy"
        :error-message="errorMessage"
        @recorded="saveRecording"
        @discard="openPicker"
    />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import VideoRecorder from 'src/components/VideoRecorder.vue';
import { useRouteNavigation } from 'src/composables/useRouteNavigation';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useCreateCaptureDraftMutation } from 'src/mutations/captureDrafts';

const { t } = useI18n();
const router = useRouter();
const route = useRoute();
const { mutate, data: draftId, isLoading, error } = useCreateCaptureDraftMutation();
const { navigating, navigationFailed, clearNavigationFailure, replace } = useRouteNavigation();
const recordingError = ref('');
const busy = computed(() => isLoading.value || navigating.value);
const errorMessage = computed(() => {
    if (recordingError.value) return recordingError.value;
    if (navigationFailed.value) return t('capture.openFailed');
    return error.value ? t('capture.draft.createFailed') : '';
});

watch(draftId, (id) => {
    if (!id) return;
    void replace({
        name: 'capture-draft',
        params: { draftId: id },
        query: { buildingId: route.query.buildingId },
    });
});

function saveRecording(recording: RecordedVideo): void {
    if (busy.value) return;
    recordingError.value = '';
    clearNavigationFailure();
    const buildingId = route.query.buildingId;
    try {
        const { file } = toCapturedVideo(recording, null);
        mutate({
            source: { video: file },
            buildingId: typeof buildingId === 'string' ? buildingId : null,
        });
    } catch (error) {
        recordingError.value = error instanceof Error ? error.message : t('capture.openFailed');
    }
}

function openPicker(): void {
    void router.replace({
        name: 'capture-new',
        query: { buildingId: route.query.buildingId },
    });
}
</script>
