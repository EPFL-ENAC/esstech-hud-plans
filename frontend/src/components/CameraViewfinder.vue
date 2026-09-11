<template>
    <section :aria-label="t('capture.camera.viewfinder')" :aria-busy="state === 'requesting'">
        <q-select
            v-if="cameras.length && !fullscreen"
            :model-value="selectedCameraId"
            :options="cameras"
            emit-value
            map-options
            outlined
            :label="t('capture.camera.label')"
            :aria-label="t('capture.camera.label')"
            class="q-mb-md"
            :disable="state === 'requesting' || isRecording || isStopping"
            :loading="loadingCameras"
            @update:model-value="selectCamera"
        >
            <template #prepend><q-icon name="videocam" /></template>
        </q-select>
        <q-banner v-if="cameraListError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ cameraListError }}
            <template #action>
                <q-btn
                    flat
                    :label="t('capture.camera.refresh')"
                    :disable="loadingCameras"
                    @click="refreshCameras"
                />
            </template>
        </q-banner>
        <q-banner v-if="recordingError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ recordingError }}
        </q-banner>
        <q-banner
            v-else-if="!recordingSupported"
            class="bg-red-1 text-negative q-mb-md"
            role="alert"
        >
            {{ t('capture.camera.recordingUnsupported') }}
        </q-banner>
        <q-card
            flat
            bordered
            square
            class="camera-viewfinder bg-black text-white"
            :class="{ 'camera-viewfinder--fullscreen': fullscreen }"
        >
            <video
                ref="videoElement"
                autoplay
                muted
                playsinline
                :aria-label="t('capture.camera.livePreview')"
                class="camera-video"
                :class="{ 'camera-video--contain': fullscreen }"
            />

            <div
                v-if="state !== 'live'"
                class="absolute-full column flex-center text-center q-pa-md bg-black"
            >
                <template v-if="state === 'requesting'">
                    <q-spinner color="primary" size="32px" class="q-mb-sm" />
                    <span role="status">{{ t('capture.camera.waitingForAccess') }}</span>
                </template>
                <template v-else-if="state === 'error'">
                    <q-icon name="videocam_off" size="32px" class="q-mb-sm" />
                    <p role="alert">{{ errorMessage }}</p>
                    <q-btn
                        v-if="canRetry"
                        :label="t('common.retry')"
                        color="primary"
                        unelevated
                        no-caps
                        @click="startCamera"
                    />
                </template>
                <template v-else>
                    <p role="status">
                        {{
                            needsPlaybackGesture
                                ? t('capture.camera.tapToStart')
                                : t('capture.camera.paused')
                        }}
                    </p>
                    <q-btn
                        v-if="needsPlaybackGesture"
                        :label="t('capture.camera.startPreview')"
                        color="primary"
                        unelevated
                        no-caps
                        :loading="startingPreview"
                        @click="playPreview"
                    />
                </template>
            </div>
        </q-card>
    </section>
</template>

<script setup lang="ts">
import {
    computed,
    onActivated,
    onBeforeUnmount,
    onDeactivated,
    onMounted,
    readonly,
    ref,
} from 'vue';
import type { RecordedVideo } from 'src/lib/captured-video';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

withDefaults(defineProps<{ fullscreen?: boolean }>(), { fullscreen: false });

type CameraState = 'requesting' | 'live' | 'paused' | 'error';

interface RecordingSession {
    recorder: MediaRecorder;
    chunks: Blob[];
    startedAt: number;
    stop: {
        promise: Promise<RecordedVideo>;
        resolve: (video: RecordedVideo) => void;
        reject: (error: Error) => void;
        durationSeconds: number;
    } | null;
}

const cameraDevices = ref<MediaDeviceInfo[]>([]);
const cameras = computed(() =>
    cameraDevices.value.map((device, index) => ({
        label: device.label.trim() || t('capture.camera.numbered', { number: index + 1 }),
        value: device.deviceId,
    })),
);
const selectedCameraId = ref<string | null>(null);
const loadingCameras = ref(false);
const cameraListError = ref('');
const videoElement = ref<HTMLVideoElement | null>(null);
const state = ref<CameraState>('paused');
const errorMessage = ref('');
const canRetry = ref(true);
const needsPlaybackGesture = ref(false);
const startingPreview = ref(false);
const recordingSupported = typeof MediaRecorder !== 'undefined';
const recordingError = ref('');
const isRecording = ref(false);
const isStopping = ref(false);
const canStartRecording = computed(
    () =>
        state.value === 'live' &&
        recordingSupported &&
        !isRecording.value &&
        !isStopping.value &&
        stream?.getVideoTracks().some((track) => track.readyState === 'live') === true,
);

let recording: RecordingSession | null = null;
let stream: MediaStream | null = null;
let active = false;
let disposed = false;
let pageHidden = false;
let pendingRequest = false;
let resumeRequested = true;
let generation = 0;
let cameraListGeneration = 0;
let cameraAccessRequested = false;

function isVisible(): boolean {
    return active && !disposed && !pageHidden && document.visibilityState === 'visible';
}

function clearRecording(): void {
    const session = recording;
    recording = null;
    isRecording.value = false;
    isStopping.value = false;
    if (!session) return;
    session.recorder.ondataavailable = null;
    session.recorder.onstop = null;
    session.recorder.onerror = null;
    session.chunks.length = 0;
    if (session.recorder.state !== 'inactive') {
        try {
            session.recorder.stop();
        } catch {
            // Cleanup must still release the camera if the recorder has failed.
        }
    }
}

function failRecording(message: string): Error {
    const error = new Error(message);
    recordingError.value = message;
    recording?.stop?.reject(error);
    clearRecording();
    return error;
}

function startRecording(): void {
    if (
        !canStartRecording.value ||
        !isVisible() ||
        !stream?.getVideoTracks().some((track) => track.readyState === 'live')
    ) {
        const message = t('capture.camera.notReady');
        recordingError.value = message;
        throw new Error(message);
    }

    recordingError.value = '';
    try {
        const recorder = new MediaRecorder(stream);
        const session: RecordingSession = {
            recorder,
            chunks: [],
            startedAt: performance.now(),
            stop: null,
        };
        recording = session;
        recorder.ondataavailable = (event) => {
            if (recording === session && event.data.size > 0) session.chunks.push(event.data);
        };
        recorder.onerror = () => {
            if (recording === session) {
                failRecording(t('capture.camera.recordingFailed'));
            }
        };
        recorder.onstop = () => {
            if (recording !== session) return;
            if (!session.stop) {
                failRecording(t('capture.camera.recordingInterrupted'));
                return;
            }
            const blob = new Blob(session.chunks, {
                type: recorder.mimeType || session.chunks[0]?.type || '',
            });
            if (blob.size === 0 || session.stop.durationSeconds <= 0) {
                failRecording(t('capture.camera.emptyRecording'));
                return;
            }
            session.stop.resolve({
                blob,
                durationSeconds: session.stop.durationSeconds,
            });
            clearRecording();
        };
        recorder.start();
        session.startedAt = performance.now();
        isRecording.value = true;
    } catch {
        throw failRecording(t('capture.camera.startRecordingFailed'));
    }
}

function stopRecording(): Promise<RecordedVideo> {
    const session = recording;
    if (session?.stop) return session.stop.promise;
    if (!session || !isRecording.value) {
        recordingError.value = t('capture.camera.noActiveRecording');
        return Promise.reject(new Error(recordingError.value));
    }

    const durationSeconds = (performance.now() - session.startedAt) / 1000;
    let resolveVideo!: (video: RecordedVideo) => void;
    let rejectVideo!: (error: Error) => void;
    const promise = new Promise<RecordedVideo>((resolve, reject) => {
        resolveVideo = resolve;
        rejectVideo = reject;
    });
    session.stop = { promise, resolve: resolveVideo, reject: rejectVideo, durationSeconds };
    isRecording.value = false;
    isStopping.value = true;
    try {
        session.recorder.stop();
    } catch {
        failRecording(t('capture.camera.finishRecordingFailed'));
    }
    return promise;
}

function releaseCamera(): void {
    if (recording) {
        failRecording(t('capture.camera.recordingInterrupted'));
    }
    if (state.value === 'live') state.value = 'paused';
    generation++;
    cameraListGeneration++;
    loadingCameras.value = false;
    if (stream) {
        for (const track of stream.getTracks()) {
            track.removeEventListener('ended', onTrackEnded);
            track.stop();
        }
        stream = null;
    }
    if (videoElement.value) {
        videoElement.value.pause();
        videoElement.value.srcObject = null;
    }
    needsPlaybackGesture.value = false;
    startingPreview.value = false;
}

async function refreshCameras(): Promise<void> {
    if (!isVisible() || !cameraAccessRequested || !navigator.mediaDevices?.enumerateDevices) return;
    const requestGeneration = ++cameraListGeneration;
    loadingCameras.value = true;
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (requestGeneration !== cameraListGeneration || !isVisible()) return;
        cameraDevices.value = devices.filter(
            (device) => device.kind === 'videoinput' && device.deviceId,
        );
        cameraListError.value = '';
        if (
            selectedCameraId.value &&
            !cameras.value.some((camera) => camera.value === selectedCameraId.value)
        ) {
            selectedCameraId.value = null;
            if (stream) {
                showError(t('capture.camera.selectedUnavailable'));
            }
        }
    } catch {
        if (requestGeneration === cameraListGeneration && isVisible()) {
            cameraListError.value = t('capture.camera.loadFailed');
        }
    } finally {
        if (requestGeneration === cameraListGeneration) loadingCameras.value = false;
    }
}

async function selectCamera(deviceId: string): Promise<void> {
    if (
        deviceId === selectedCameraId.value ||
        pendingRequest ||
        isRecording.value ||
        isStopping.value ||
        !isVisible()
    )
        return;
    selectedCameraId.value = deviceId;
    releaseCamera();
    await startCamera();
}

function onDevicesChanged(): void {
    void refreshCameras();
}

function showError(message: string, retry = true): void {
    releaseCamera();
    resumeRequested = false;
    errorMessage.value = message;
    canRetry.value = retry;
    state.value = 'error';
}

function cameraErrorMessage(error: unknown): string {
    switch (error instanceof DOMException ? error.name : '') {
        case 'NotAllowedError':
        case 'SecurityError':
            return t('capture.camera.accessDenied');
        case 'NotFoundError':
        case 'OverconstrainedError':
            return t('capture.camera.notFound');
        case 'NotReadableError':
        case 'AbortError':
            return t('capture.camera.openFailed');
        default:
            return t('capture.camera.startFailed');
    }
}

async function playPreview(): Promise<void> {
    const video = videoElement.value;
    if (!video || !stream || !isVisible() || startingPreview.value) return;
    const playbackGeneration = generation;
    startingPreview.value = true;
    try {
        video.muted = true;
        await video.play();
        if (playbackGeneration !== generation || !isVisible()) return;
        needsPlaybackGesture.value = false;
        state.value = 'live';
    } catch (error) {
        if (playbackGeneration !== generation || !isVisible()) return;
        if (error instanceof DOMException && error.name === 'NotAllowedError') {
            needsPlaybackGesture.value = true;
            state.value = 'paused';
        } else {
            showError(t('capture.camera.previewFailed'));
        }
    } finally {
        if (playbackGeneration === generation) startingPreview.value = false;
    }
}

async function startCamera(): Promise<void> {
    if (!isVisible() || pendingRequest || stream) return;
    if (!window.isSecureContext) {
        showError(t('capture.camera.secureConnectionRequired'), false);
        return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
        showError(t('capture.camera.accessUnsupported'), false);
        return;
    }

    const requestGeneration = ++generation;
    pendingRequest = true;
    resumeRequested = false;
    errorMessage.value = '';
    state.value = 'requesting';
    cameraAccessRequested = true;
    try {
        const constraints: MediaStreamConstraints = {
            audio: false,
            video: selectedCameraId.value
                ? { deviceId: { exact: selectedCameraId.value } }
                : { facingMode: { ideal: 'environment' } },
        };
        const acquiredStream = await navigator.mediaDevices.getUserMedia(constraints);
        // Permission requests cannot be cancelled. Never retain a late grant.
        if (requestGeneration !== generation || !isVisible()) {
            acquiredStream.getTracks().forEach((track) => track.stop());
            return;
        }
        stream = acquiredStream;
        const videoTrack = stream.getVideoTracks()[0];
        if (!videoTrack || videoTrack.readyState === 'ended') {
            onTrackEnded();
            return;
        }
        videoTrack.addEventListener('ended', onTrackEnded);
        selectedCameraId.value = videoTrack.getSettings().deviceId || selectedCameraId.value;
        videoElement.value!.srcObject = stream;
        // Playback has its own generation guard and must not hold up a new
        // camera request if the page is hidden before play() settles.
        void playPreview();
        void refreshCameras();
    } catch (error) {
        // A denial received while hidden must still require an explicit retry.
        if (!disposed) {
            showError(cameraErrorMessage(error));
            void refreshCameras();
        }
    } finally {
        pendingRequest = false;
        if (resumeRequested && isVisible()) void startCamera();
    }
}

function onTrackEnded(): void {
    showError(t('capture.camera.previewInterrupted'));
    void refreshCameras();
}

function suspendCamera(): void {
    if (stream || pendingRequest) resumeRequested = true;
    releaseCamera();
    if (state.value !== 'error') state.value = 'paused';
}

function updateActivity(): void {
    if (!isVisible()) suspendCamera();
    else if (resumeRequested) void startCamera();
    else void refreshCameras();
}

function onPageHide(): void {
    pageHidden = true;
    suspendCamera();
}

function onPageShow(): void {
    pageHidden = false;
    updateActivity();
}

onMounted(() => {
    active = true;
    document.addEventListener('visibilitychange', updateActivity);
    navigator.mediaDevices?.addEventListener('devicechange', onDevicesChanged);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    updateActivity();
});
onActivated(() => {
    active = true;
    updateActivity();
});
onDeactivated(() => {
    active = false;
    suspendCamera();
});
onBeforeUnmount(() => {
    disposed = true;
    active = false;
    resumeRequested = false;
    document.removeEventListener('visibilitychange', updateActivity);
    navigator.mediaDevices?.removeEventListener('devicechange', onDevicesChanged);
    window.removeEventListener('pagehide', onPageHide);
    window.removeEventListener('pageshow', onPageShow);
    releaseCamera();
});

defineExpose({
    startRecording,
    stopRecording,
    canStartRecording,
    isRecording: readonly(isRecording),
    isStopping: readonly(isStopping),
});
</script>

<style scoped>
.camera-viewfinder {
    width: 100%;
    aspect-ratio: 16 / 9;
    max-height: 420px;
    overflow: hidden;
}

.camera-video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
}

/* Full-screen record page: the camera fills the whole viewport. */
.camera-viewfinder--fullscreen {
    width: 100vw;
    height: 100vh;
    aspect-ratio: auto;
    max-height: none;
}

.camera-video--contain {
    /* The video box fills the viewport and the whole camera image stays
       visible. The black page background fills the leftover bars, so no
       part of the image is cropped. */
    object-fit: contain;
}
</style>
