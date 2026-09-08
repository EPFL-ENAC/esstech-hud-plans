<template>
    <section aria-label="Input video" class="q-gutter-y-sm">
        <div class="text-subtitle2">Input video</div>

        <div v-if="loading" role="status" class="row items-center q-gutter-sm">
            <q-spinner color="primary" size="24px" />
            <span>Loading video…</span>
            <q-btn flat dense label="Cancel" @click="cancel" />
        </div>

        <q-banner v-else-if="errorMessage" rounded class="bg-red-1 text-negative" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat color="negative" label="Retry" @click="retry" />
            </template>
        </q-banner>

        <video
            v-else-if="videoUrl"
            ref="videoElement"
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
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionVideoQuery } from 'src/queries/reconstructions';

const props = withDefaults(
    defineProps<{
        buildingId: string;
        reconstructionId: string;
        active?: boolean;
    }>(),
    { active: true },
);

const query = useReconstructionVideoQuery(
    toRef(props, 'buildingId'),
    toRef(props, 'reconstructionId'),
);
const videoElement = ref<HTMLVideoElement | null>(null);
const videoUrl = ref<string | null>(null);
const playbackError = ref('');
const errorDismissed = ref(false);
const loading = query.isLoading;
const errorMessage = computed(() => {
    if (playbackError.value) return playbackError.value;
    const error = query.error.value;
    if (!error || errorDismissed.value) return '';
    if (error instanceof ApiError && error.status === 404)
        return 'The input video is not available.';
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        return 'Unable to access this video. Please sign in again.';
    }
    return 'Unable to load the video. Please try again.';
});

function releaseVideo(): void {
    videoElement.value?.pause();
    if (videoUrl.value) URL.revokeObjectURL(videoUrl.value);
    videoUrl.value = null;
}

watch(
    query.data,
    (blob) => {
        releaseVideo();
        if (blob) videoUrl.value = URL.createObjectURL(blob);
    },
    { immediate: true },
);

async function load(): Promise<void> {
    if (loading.value) return;
    playbackError.value = '';
    errorDismissed.value = false;
    if (!videoUrl.value && query.data.value) {
        videoUrl.value = URL.createObjectURL(query.data.value);
    }
    // refresh reuses a fresh Blob or deduplicates an in-flight download.
    // Only the scoped data watcher creates URLs when a download finishes.
    await query.refresh();
}

async function retry(): Promise<void> {
    playbackError.value = '';
    errorDismissed.value = false;
    await query.refetch();
}

function cancel(): void {
    query.cancel();
    playbackError.value = '';
    errorDismissed.value = true;
}

function onPlaybackError(): void {
    releaseVideo();
    playbackError.value =
        'This video could not be played. Its format may not be supported by your browser.';
}

watch(
    () => props.active,
    (active) => {
        if (!active) videoElement.value?.pause();
    },
    { flush: 'sync' },
);
watch(
    () => [props.buildingId, props.reconstructionId],
    () => {
        playbackError.value = '';
        errorDismissed.value = false;
    },
);
onBeforeUnmount(releaseVideo);
defineExpose({ load });
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
