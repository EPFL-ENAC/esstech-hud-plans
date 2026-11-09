<template>
    <video-recorder :error-message="errorMessage" @recorded="saveRecording" @discard="openPicker" />
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import VideoRecorder from 'src/components/VideoRecorder.vue';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useCaptureDraftsStore } from 'src/stores/captureDrafts';

const { t } = useI18n();
const router = useRouter();
const route = useRoute();
const { createDraft } = useCaptureDraftsStore();
const errorMessage = ref('');

async function saveRecording(recording: RecordedVideo): Promise<void> {
    errorMessage.value = '';
    try {
        const { file } = toCapturedVideo(recording, null);
        const draftId = createDraft({ video: file });
        await router.replace({
            name: 'capture-draft',
            params: { draftId },
            query: { buildingId: route.query.buildingId },
        });
    } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : t('capture.openFailed');
    }
}

function openPicker(): void {
    void router.replace({
        name: 'capture-new',
        query: { buildingId: route.query.buildingId },
    });
}
</script>
