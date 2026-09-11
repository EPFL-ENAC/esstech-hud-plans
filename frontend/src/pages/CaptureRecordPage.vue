<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="capture-record-page">
                <camera-viewfinder ref="viewfinder" fullscreen />

                <div
                    v-if="isRecording"
                    class="record-timer"
                    role="timer"
                    :aria-label="t('capture.record.elapsed', { time: formattedElapsed })"
                >
                    <span class="record-timer-dot" aria-hidden="true" />
                    <span>{{ formattedElapsed }}</span>
                </div>

                <q-banner
                    v-if="handoffError"
                    class="record-status bg-red-1 text-negative q-py-sm"
                    role="alert"
                >
                    {{ handoffError }}
                </q-banner>

                <div class="record-controls">
                    <q-btn
                        round
                        class="record-btn-close"
                        icon="close"
                        :aria-label="t('capture.record.close')"
                        @click="confirmDiscard"
                    />
                    <q-btn
                        round
                        class="record-btn-rec"
                        :aria-label="
                            isRecording ? t('capture.record.stop') : t('capture.record.record')
                        "
                        :disable="busy || !(isRecording || viewfinder?.canStartRecording)"
                        :loading="busy || viewfinder?.isStopping"
                        @click="toggleRecording"
                    >
                        <template #default>
                            <span
                                class="record-btn-core"
                                :class="{ 'record-btn-core--stop': isRecording }"
                            />
                        </template>
                    </q-btn>
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import CameraViewfinder from 'src/components/CameraViewfinder.vue';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useCaptureStore } from 'src/stores/capture';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const viewfinder = useTemplateRef<InstanceType<typeof CameraViewfinder>>('viewfinder');
const router = useRouter();
const $q = useQuasar();
const captureStore = useCaptureStore();
const busy = ref(false);
const handoffError = ref('');
const elapsedSeconds = ref(0);
let disposed = false;
let recordingStartedAt = 0;
let timerId: number | null = null;

const isRecording = computed(() => viewfinder.value?.isRecording ?? false);

const formattedElapsed = computed(() => {
    const total = Math.floor(elapsedSeconds.value);
    const minutes = String(Math.floor(total / 60)).padStart(2, '0');
    const seconds = String(total % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
});

watch(isRecording, (recording) => {
    if (timerId !== null) {
        window.clearInterval(timerId);
        timerId = null;
    }
    if (recording) {
        // The timer restarts with each recording so the chip only shows the
        // duration of the current recording.
        elapsedSeconds.value = 0;
        recordingStartedAt = performance.now();
        timerId = window.setInterval(() => {
            elapsedSeconds.value = (performance.now() - recordingStartedAt) / 1000;
        }, 250);
    }
});

async function toggleRecording(): Promise<void> {
    const camera = viewfinder.value;
    if (!camera || busy.value || disposed) return;
    handoffError.value = '';
    if (!camera.isRecording) {
        try {
            camera.startRecording();
        } catch {
            // Recording failures are displayed by the viewfinder.
        }
        return;
    }

    busy.value = true;
    try {
        let recording: RecordedVideo;
        try {
            recording = await camera.stopRecording();
        } catch {
            // Includes interruption while the final data is being collected.
            return;
        }
        if (disposed) return;
        // No automatic location ask after a stop: the video hands off
        // without a location and the capture form opens at once.
        captureStore.setVideo(toCapturedVideo(recording, null));
        const failure = await router.push('/capture/new');
        if (failure) {
            captureStore.clearVideo();
            if (!disposed) handoffError.value = t('capture.handoffFailed');
        }
    } catch (error) {
        captureStore.clearVideo();
        if (!disposed) {
            handoffError.value = error instanceof Error ? error.message : t('capture.openFailed');
        }
    } finally {
        busy.value = false;
    }
}

function confirmDiscard(): void {
    // Going back loses the current capture, so an explicit confirmation
    // protects an in-progress recording from an accidental close.
    $q.dialog({
        title: t('capture.record.discardTitle'),
        message: t('capture.record.discardMessage'),
        ok: {
            label: t('capture.record.discard'),
            color: 'negative',
            noCaps: true,
        },
        cancel: {
            label: t('capture.record.keep'),
            flat: true,
            noCaps: true,
        },
        dark: true,
    }).onOk(() => {
        void discardCapture();
    });
}

async function discardCapture(): Promise<void> {
    // An in-progress recorder is discarded by the viewfinder's unmount
    // cleanup when the page unloads.
    captureStore.clearVideo();
    if (router.options.history.state?.back) {
        router.back();
    } else {
        await router.push('/capture/video');
    }
}

onBeforeUnmount(() => {
    disposed = true;
    if (timerId !== null) {
        window.clearInterval(timerId);
        timerId = null;
    }
});
</script>

<style scoped>
.capture-record-page {
    position: relative;
    background-color: #000000;
}

/* Translucent pill with a pulsing dot so the user sees the recording is
   running and how long it has been running. */
.record-timer {
    position: absolute;
    top: 16px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.6);
    color: #ffffff;
    font-size: 0.95rem;
    font-variant-numeric: tabular-nums;
}

.record-timer-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #ff3b30;
    animation: record-pulse 1s ease-in-out infinite;
}

@keyframes record-pulse {
    0%,
    100% {
        opacity: 1;
    }
    50% {
        opacity: 0.3;
    }
}

/* Status and error messages sit just above the control bar. */
.record-status {
    position: absolute;
    left: 16px;
    right: 16px;
    bottom: 88px;
    z-index: 10;
}

/* Camera control bar: the record button stays centered and the close button
   sits on the left, like a native camera app. */
.record-controls {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 72px;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.9);
}

.record-btn-close {
    position: absolute;
    left: 24px;
    width: 44px;
    height: 44px;
    padding: 0 !important;
    min-width: auto;
    color: #ffffff;
    background: rgba(255, 255, 255, 0.2);
}

.record-btn-rec {
    width: 72px;
    height: 72px;
    padding: 0 !important;
    min-width: auto;
    background: transparent;
    border: 5px solid #ffffff;
}

/* Inner core of the record button: a filled circle while idle, a rounded
   square while recording, like the iOS camera stop control. */
.record-btn-core {
    display: block;
    width: 52px;
    height: 52px;
    border-radius: 50%;
    background: #ff3b30;
    transition: all 0.15s;
}

.record-btn-core--stop {
    width: 38px;
    height: 38px;
    border-radius: 8px;
}
</style>
