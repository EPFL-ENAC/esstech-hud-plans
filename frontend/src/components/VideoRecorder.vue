<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="video-recorder-page">
                <camera-viewfinder ref="viewfinder" fullscreen />
                <video-tips-modal v-model="showTips" />

                <div
                    v-if="isRecording"
                    class="record-timer"
                    role="timer"
                    :aria-label="t('capture.record.elapsed', { time: formattedElapsed })"
                >
                    <span class="record-timer-dot" aria-hidden="true" />
                    <span>{{ formattedElapsed }}</span>
                </div>

                <div class="record-controls">
                    <q-banner
                        v-if="errorMessage"
                        class="record-status bg-red-1 text-negative q-py-sm"
                        role="alert"
                    >
                        {{ errorMessage }}
                        <template #action>
                            <slot name="error-actions" />
                        </template>
                    </q-banner>

                    <div class="record-actions">
                        <q-btn
                            round
                            class="record-btn-close"
                            icon="close"
                            :aria-label="t('capture.record.close')"
                            :disable="controlsBusy"
                            @click="confirmDiscard"
                        />
                        <q-btn
                            round
                            class="record-btn-rec"
                            :aria-label="
                                isRecording ? t('capture.record.stop') : t('capture.record.record')
                            "
                            :disable="
                                controlsBusy ||
                                recordingDisabled ||
                                !(isRecording || viewfinder?.canStartRecording)
                            "
                            :loading="controlsBusy || viewfinder?.isStopping"
                            @click="toggleRecording"
                        >
                            <template #default>
                                <span
                                    class="record-btn-core"
                                    :class="{ 'record-btn-core--stop': isRecording }"
                                />
                            </template>
                        </q-btn>
                        <q-btn
                            round
                            class="record-btn-tips"
                            icon="lightbulb_outline"
                            :aria-label="t('capture.tipsTitle')"
                            :disable="controlsBusy || isRecording || viewfinder?.isStopping"
                            @click="showTips = true"
                        />
                    </div>

                    <!-- Numbered camera buttons float above the record
                         button, over the video, outside the dark panel. -->
                    <camera-picker
                        v-if="viewfinder"
                        class="record-camera-strip"
                        :cameras="viewfinder.cameras"
                        :selected-camera-id="viewfinder.selectedCameraId"
                        :disabled="controlsBusy || recordingDisabled || !viewfinder.canSelectCamera"
                        fullscreen
                        @select-camera="viewfinder.selectCamera($event)"
                    />
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue';
import { useQuasar } from 'quasar';
import CameraViewfinder from 'src/components/CameraViewfinder.vue';
import CameraPicker from 'src/components/CameraPicker.vue';
import VideoTipsModal from 'src/components/VideoTipsModal.vue';
import type { RecordedVideo } from 'src/lib/captured-video';
import { useLocalPreferencesStore } from 'src/stores/localPreferences';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const viewfinder = useTemplateRef<InstanceType<typeof CameraViewfinder>>('viewfinder');
const $q = useQuasar();
const props = withDefaults(
    defineProps<{
        busy?: boolean;
        recordingDisabled?: boolean;
        errorMessage?: string;
    }>(),
    {
        busy: false,
        recordingDisabled: false,
        errorMessage: '',
    },
);
const emit = defineEmits<{
    recorded: [video: RecordedVideo];
    discard: [];
}>();
const stopping = ref(false);
const controlsBusy = computed(() => props.busy || stopping.value);
const localPreferencesStore = useLocalPreferencesStore();
const showTips = ref(!localPreferencesStore.hideVideoTips);
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
    if (!camera || controlsBusy.value || props.recordingDisabled || disposed) return;

    if (!camera.isRecording) {
        try {
            camera.startRecording();
        } catch {
            // Recording failures are displayed by the viewfinder.
        }
        return;
    }

    stopping.value = true;
    try {
        const recording = await camera.stopRecording();
        if (!disposed) emit('recorded', recording);
    } catch {
        // Includes interruption while the final data is being collected.
    } finally {
        stopping.value = false;
    }
}

function confirmDiscard(): void {
    if (controlsBusy.value || disposed) return;
    if (props.recordingDisabled) {
        emit('discard');
        return;
    }
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
        if (!disposed && !controlsBusy.value) emit('discard');
    });
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
.video-recorder-page {
    position: relative;
    background-color: #000000;
}

/* Translucent pill with a pulsing dot so the user sees the recording is
   running and how long it has been running. */
.record-timer {
    position: absolute;
    top: calc(16px + env(safe-area-inset-top));
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

.record-status {
    margin: 8px 16px;
}

/* The camera choice strip floats above the record button and shows the
   video behind it, so it has no background color of its own. */
.record-camera-strip {
    position: absolute;
    bottom: calc(100% + 8px);
    left: 0;
    right: 0;
}

.record-controls {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 10;
    background: rgba(0, 0, 0, 0.9);
    padding-bottom: env(safe-area-inset-bottom);
    padding-left: env(safe-area-inset-left);
    padding-right: env(safe-area-inset-right);
}

/* Keep the record button centered between the close and tips buttons. */
.record-actions {
    position: relative;
    height: 72px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.record-btn-close,
.record-btn-tips {
    position: absolute;
    width: 44px;
    height: 44px;
    padding: 0 !important;
    min-width: auto;
    color: #ffffff;
    background: rgba(255, 255, 255, 0.2);
}

.record-btn-close {
    left: 24px;
}

.record-btn-tips {
    right: 24px;
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
