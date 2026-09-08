<template>
    <div class="reconstruction-settings q-gutter-y-md">
        <div class="text-subtitle1 text-weight-bold">Video frames (FFmpeg)</div>
        <div class="row q-col-gutter-md">
            <q-input
                v-model.number="settings.ffmpeg.fps"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="0.01"
                step="0.01"
                label="FPS"
            />
            <q-input
                v-model.number="settings.ffmpeg.fit_in_width"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="1"
                step="1"
                label="Fit-in width"
            />
            <q-input
                v-model.number="settings.ffmpeg.fit_in_height"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="1"
                step="1"
                label="Fit-in height"
            />
        </div>

        <q-separator />
        <frame-picker-settings v-model="settings.framePicker" embedded />
        <q-separator />

        <div class="text-subtitle1 text-weight-bold">Camera reconstruction (COLMAP)</div>
        <div class="row q-col-gutter-md">
            <q-select
                v-model="settings.colmap.data_type"
                class="col-12 col-sm-6"
                outlined
                emit-value
                map-options
                :options="colmapDataTypeOptions"
                label="Data type"
            />
            <q-select
                v-model="settings.colmap.quality"
                class="col-12 col-sm-6"
                outlined
                :options="colmapQualityOptions"
                label="Quality"
            />
            <q-select
                v-model="settings.colmap.camera_model"
                class="col-12 col-sm-6"
                outlined
                :options="colmapCameraModelOptions"
                label="Camera model"
            />
        </div>
        <div class="row q-col-gutter-md">
            <q-toggle
                v-model="settings.colmap.single_camera"
                class="col-12 col-sm-6"
                label="Use shared camera intrinsics"
            />
            <q-toggle v-model="settings.colmap.use_gpu" class="col-12 col-sm-6" label="Use GPU" />
            <q-toggle
                v-model="settings.colmap.use_global_mapper"
                class="col-12 col-sm-6"
                label="Use global mapper"
            />
        </div>

        <q-separator />
        <brush-settings v-model="settings.brush" embedded />
    </div>
</template>

<script setup lang="ts">
import BrushSettings from 'src/components/BrushSettings.vue';
import FramePickerSettings from 'src/components/FramePickerSettings.vue';
import type { ReconstructionSettingsConfig } from 'src/lib/reconstruction-settings';

const settings = defineModel<ReconstructionSettingsConfig>({ required: true });

const colmapDataTypeOptions = [
    { label: 'Individual images', value: 'individual' },
    { label: 'Video frames', value: 'video' },
    { label: 'Internet images', value: 'internet' },
];
const colmapQualityOptions = ['low', 'medium', 'high', 'extreme'];
const colmapCameraModelOptions = ['PINHOLE', 'OPENCV', 'OPENCV_FISHEYE', 'RADIAL'];
</script>

<style scoped>
.reconstruction-settings {
    container-type: inline-size;
}

@container (max-width: 480px) {
    .reconstruction-settings :deep(.row > .col-sm-6) {
        width: 100%;
    }
}
</style>
