<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header title="Capture video" />

        <camera-viewfinder ref="viewfinder" class="q-mb-md" />

        <section class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-lg">Tips for best results</h2>
            <q-list class="q-gutter-y-md">
                <q-card
                    v-for="tip in tips"
                    :key="tip.icon"
                    flat
                    bordered
                    class="q-py-sm items-center"
                >
                    <q-item>
                        <q-item-section avatar>
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon :name="tip.icon" />
                            </q-avatar>
                        </q-item-section>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium">{{
                                tip.title
                            }}</q-item-label>
                            <q-item-label caption>{{ tip.meta }}</q-item-label>
                        </q-item-section>
                    </q-item>
                </q-card>
            </q-list>
        </section>

        <q-banner v-if="handoffError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ handoffError }}
        </q-banner>

        <q-btn
            :label="viewfinder?.isRecording ? 'Stop Recording' : 'Start Recording'"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            :disable="busy || !(viewfinder?.isRecording || viewfinder?.canStartRecording)"
            :loading="busy || viewfinder?.isStopping"
            @click="toggleRecording"
        />
    </q-page>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, useTemplateRef } from 'vue';
import { useRouter } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import CameraViewfinder from 'src/components/CameraViewfinder.vue';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useCaptureStore } from 'src/stores/capture';

const viewfinder = useTemplateRef<InstanceType<typeof CameraViewfinder>>('viewfinder');
const router = useRouter();
const captureStore = useCaptureStore();
const busy = ref(false);
const handoffError = ref('');
let disposed = false;

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
        captureStore.setVideo(toCapturedVideo(recording));
        const failure = await router.push('/capture/new');
        if (failure) {
            captureStore.clearVideo();
            if (!disposed) handoffError.value = 'Could not open New Capture. Please record again.';
        }
    } catch (error) {
        captureStore.clearVideo();
        if (!disposed) {
            handoffError.value =
                error instanceof Error ? error.message : 'Could not open New Capture.';
        }
    } finally {
        busy.value = false;
    }
}

onBeforeUnmount(() => {
    disposed = true;
});

const tips = ref([
    { icon: 'photo_camera', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'timer', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'swap_vert', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'fullscreen', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
]);
</script>
