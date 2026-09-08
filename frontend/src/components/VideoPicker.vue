<template>
    <div class="q-gutter-y-md">
        <q-file
            v-model="file"
            outlined
            clearable
            accept="video/*"
            :label="t('capture.video.choose')"
        >
            <template #prepend><q-icon name="movie" /></template>
        </q-file>

        <video
            v-if="previewUrl"
            :key="previewUrl"
            :src="previewUrl"
            controls
            playsinline
            preload="metadata"
            :aria-label="t('capture.video.preview')"
            class="video-preview"
            @loadedmetadata="onMetadataLoaded"
            @error="onPreviewError"
        />

        <div v-if="metadata" class="text-primary">
            {{ metadata.duration }} &nbsp; {{ metadata.size }}
        </div>

        <q-banner v-if="errorMessage" class="bg-red-1 text-negative" role="alert">
            {{ errorMessage }}
        </q-banner>
    </div>
</template>

<script lang="ts">
export type { VideoMetadata } from './VideoPicker.types';
</script>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import type { VideoMetadata } from './VideoPicker.types';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const props = defineProps<{
    fallbackDurationSeconds?: number | undefined;
}>();
const file = defineModel<File | null>({ default: null });
const emit = defineEmits<{
    metadata: [value: VideoMetadata | null];
}>();

const previewUrl = ref<string | null>(null);
const metadata = ref<VideoMetadata | null>(null);
const errorMessage = ref('');

function updateMetadata(value: VideoMetadata | null): void {
    metadata.value = value;
    emit('metadata', value);
}

function releasePreview(): void {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
    previewUrl.value = null;
}

function currentVideo(event: Event): HTMLVideoElement | null {
    const video = event.target;
    // Replaced previews can still dispatch queued media events.
    return video instanceof HTMLVideoElement && video.getAttribute('src') === previewUrl.value
        ? video
        : null;
}

function formatDuration(duration: number): string {
    const seconds = Math.floor(duration);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = String(seconds % 60).padStart(2, '0');
    return hours
        ? `${hours}:${String(minutes).padStart(2, '0')}:${remainder}`
        : `${minutes}:${remainder}`;
}

function onMetadataLoaded(event: Event): void {
    const video = currentVideo(event);
    if (!video || !file.value || errorMessage.value) return;

    const duration =
        Number.isFinite(video.duration) && video.duration > 0
            ? video.duration
            : props.fallbackDurationSeconds;
    if (duration === undefined || !Number.isFinite(duration) || duration <= 0) {
        updateMetadata(null);
        errorMessage.value = t('capture.video.durationFailed');
        return;
    }

    updateMetadata({
        duration: formatDuration(duration),
        size: t('capture.video.size', { size: (file.value.size / 1_000_000).toFixed(2) }),
    });
}

function onPreviewError(event: Event): void {
    if (!currentVideo(event)) return;
    updateMetadata(null);
    errorMessage.value = t('capture.video.playbackFailed');
}

watch(
    file,
    (selectedFile) => {
        updateMetadata(null);
        errorMessage.value = '';
        releasePreview();
        if (selectedFile) previewUrl.value = URL.createObjectURL(selectedFile);
    },
    { immediate: true, flush: 'sync' },
);

onBeforeUnmount(releasePreview);
</script>

<style scoped>
.video-preview {
    display: block;
    width: 100%;
    max-height: 300px;
    background: #000;
}
</style>
