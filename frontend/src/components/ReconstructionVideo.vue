<template>
    <section aria-label="Input video" class="q-gutter-y-sm">
        <div class="text-subtitle2">Input video</div>

        <div v-if="loading" role="status" class="row items-center q-gutter-sm">
            <q-spinner color="primary" size="24px" />
            <span>Loading video…</span>
            <q-btn flat dense label="Cancel" @click="reset" />
        </div>

        <q-banner v-else-if="errorMessage" rounded class="bg-red-1 text-negative" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat color="negative" label="Retry" @click="load" />
            </template>
        </q-banner>

        <video
            v-else-if="videoUrl"
            :src="videoUrl"
            controls
            playsinline
            preload="metadata"
            aria-label="Reconstruction input video"
            class="reconstruction-video"
            @error="onPlaybackError"
        >
            Your browser does not support video playback.
        </video>

        <q-btn v-else outline color="primary" icon="play_circle" label="Load video" @click="load" />
    </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { ApiError, getReconstructionVideo } from 'src/lib/buildings';

const props = defineProps<{
    buildingId: string;
    reconstructionId: string;
}>();

const videoUrl = ref<string | null>(null);
const loading = ref(false);
const errorMessage = ref('');
let pendingRequest: AbortController | null = null;

function reset(): void {
    pendingRequest?.abort();
    pendingRequest = null;
    if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
    videoUrl.value = null;
    loading.value = false;
    errorMessage.value = '';
}

async function load(): Promise<void> {
    reset();
    const controller = new AbortController();
    pendingRequest = controller;
    loading.value = true;

    try {
        const video = await getReconstructionVideo(
            props.buildingId,
            props.reconstructionId,
            controller.signal,
        );
        if (!controller.signal.aborted) videoUrl.value = URL.createObjectURL(video);
    } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
            errorMessage.value = 'The input video is not available.';
        } else if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            errorMessage.value = 'Unable to access this video. Please sign in again.';
        } else {
            errorMessage.value = 'Unable to load the video. Please try again.';
        }
    } finally {
        if (pendingRequest === controller) {
            pendingRequest = null;
            loading.value = false;
        }
    }
}

function onPlaybackError(): void {
    reset();
    errorMessage.value =
        'This video could not be played. Its format may not be supported by your browser.';
}

watch(() => [props.buildingId, props.reconstructionId], reset);
onBeforeUnmount(reset);
</script>

<style scoped>
.reconstruction-video {
    display: block;
    width: 100%;
    max-height: 65vh;
    border-radius: 4px;
    background: #000;
}
</style>
