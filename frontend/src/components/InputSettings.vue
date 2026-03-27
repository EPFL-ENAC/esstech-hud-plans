<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { type InputConfig, makeDefaultInputConfig } from '../lib/splats/input';

const config = defineModel<InputConfig>({
    required: true,
    default: makeDefaultInputConfig(),
});
const activeTab = defineModel<'video' | 'colmap'>('tab', {
    default: 'video',
});

const videoPreviewUrl = ref<string | null>(null);

watch(activeTab, (newTab) => {
    config.value.type = newTab === 'video' ? 'video' : 'colmap';
});

const handleFileChange = (file: File | null) => {
    if (videoPreviewUrl.value) {
        URL.revokeObjectURL(videoPreviewUrl.value);
        videoPreviewUrl.value = null;
    }

    if (file) {
        videoPreviewUrl.value = URL.createObjectURL(file);
    }
};

onBeforeUnmount(() => {
    if (videoPreviewUrl.value) {
        URL.revokeObjectURL(videoPreviewUrl.value);
    }
});
</script>

<template>
    <q-card flat bordered class="q-pa-md q-mb-md">
        <q-card-section>
            <div class="text-h6 text-weight-light">Input</div>
            <div class="text-caption text-grey">
                Choose an input video, or start from an existing COLMAP reconstruction.
            </div>
        </q-card-section>

        <q-separator />

        <q-tabs
            v-model="activeTab"
            dense
            class="text-grey"
            active-color="primary"
            indicator-color="primary"
            narrow-indicator
        >
            <q-tab name="video" label="Video" />
            <q-tab name="colmap" label="Existing COLMAP output" />
        </q-tabs>

        <q-separator />

        <q-tab-panels v-model="activeTab" animated>
            <q-tab-panel name="video">
                <div class="text-subtitle2 text-primary q-mb-md">Input Video</div>
                <q-file
                    v-model="config.selectedVideoFile"
                    label="Select video source"
                    filled
                    clearable
                    accept="video/*"
                    @update:model-value="handleFileChange"
                >
                    <template v-slot:prepend>
                        <q-icon name="movie" />
                    </template>
                </q-file>

                <q-input
                    v-model="config.deviceName"
                    label="Device name (brand & model)"
                    filled
                    clearable
                    class="q-mt-md"
                />

                <q-select
                    v-model="config.cameraType"
                    :options="[
                        { label: 'Standard', value: 'standard' },
                        { label: 'Wide-angle', value: 'wide_angle' },
                        { label: 'Zoom', value: 'zoom' },
                    ]"
                    label="Camera Type"
                    hint="If unknown, leave as standard."
                    filled
                    emit-value
                    map-options
                    class="q-mt-md"
                />

                <div
                    v-if="videoPreviewUrl"
                    class="q-mt-md overflow-hidden rounded-borders border-grey"
                >
                    <div class="text-caption text-grey-7 q-mb-xs">Preview:</div>
                    <video
                        :src="videoPreviewUrl"
                        controls
                        class="full-width rounded-borders shadow-2"
                        style="max-height: 300px; background: black"
                    ></video>
                </div>
            </q-tab-panel>

            <q-tab-panel name="colmap">
                <q-input
                    v-model="config.colmapGenerationId"
                    label="Pipeline generation ID"
                    hint="Enter the ID of a previous reconstruction pipeline to use an existing COLMAP output."
                    filled
                    clearable
                />
            </q-tab-panel>
        </q-tab-panels>
    </q-card>
</template>

<style scoped>
.text-subtitle2 {
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.75rem;
}
</style>
