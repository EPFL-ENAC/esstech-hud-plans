<template>
    <section :aria-label="t('reconstructions.video.title')" class="q-gutter-y-sm">
        <div class="text-subtitle2">{{ t('reconstructions.video.title') }}</div>

        <div v-if="loading" role="status" class="row items-center q-gutter-sm">
            <q-spinner color="primary" size="24px" />
            <span>{{ t('reconstructions.video.loading') }}</span>
            <q-btn flat dense :label="t('common.cancel')" @click="cancel" />
        </div>

        <q-banner v-else-if="errorMessage" rounded class="bg-red-1 text-negative" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat color="negative" :label="t('common.retry')" @click="retry" />
            </template>
        </q-banner>

        <video
            v-else-if="videoUrl"
            ref="videoElement"
            :src="videoUrl"
            controls
            playsinline
            preload="metadata"
            :aria-label="t('reconstructions.video.label')"
            class="reconstruction-video"
            @error="onPlaybackError"
        >
            {{ t('reconstructions.video.unsupported') }}
        </video>

        <q-btn
            v-else
            outline
            color="primary"
            icon="play_circle"
            :label="t('reconstructions.video.load')"
            @click="load"
        />
    </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionVideoQuery } from 'src/queries/reconstructions';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

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
        return t('reconstructions.video.unavailable');
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        return t('reconstructions.video.accessDenied');
    }
    return t('reconstructions.video.loadFailed');
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
    playbackError.value = t('reconstructions.video.playbackFailed');
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
