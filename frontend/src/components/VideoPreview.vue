<template>
    <div v-if="file" class="video-preview-panel">
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

        <div class="video-details">
            <span class="video-filename">{{ file.name }}</span>
            <span v-if="metadata" class="video-metadata">
                {{ metadata.duration }} &nbsp; {{ metadata.size }}
            </span>
        </div>

        <q-banner v-if="errorMessage" class="video-error" role="alert">
            {{ errorMessage }}
        </q-banner>
    </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import type { VideoMetadata } from './VideoPreview.types';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const props = defineProps<{
    file: File | null;
    disable?: boolean;
    fallbackDurationSeconds?: number | undefined;
}>();
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
    if (!video || !props.file || errorMessage.value) return;

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
        size: t('capture.video.size', { size: (props.file.size / 1_000_000).toFixed(2) }),
    });
}

function onPreviewError(event: Event): void {
    if (!currentVideo(event)) return;
    updateMetadata(null);
    errorMessage.value = t('capture.video.playbackFailed');
}

watch(
    () => props.file,
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
.video-preview-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.video-details {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.video-description {
    display: flex;
    justify-content: space-between;
    min-width: 0;
    gap: 2rem;
}

.video-filename {
    overflow-wrap: anywhere;
}

.video-metadata {
    color: var(--q-primary);
}

.video-error {
    background: #ffebee;
    color: var(--q-negative);
}

.video-preview {
    display: block;
    width: 100%;
    max-height: 300px;
    background: #000;
}
</style>
