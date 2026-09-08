<template>
    <div class="reconstruction-settings q-gutter-y-md">
        <div class="text-subtitle1 text-weight-bold">{{ t('settings.frames.title') }}</div>
        <div class="row q-col-gutter-md">
            <q-input
                v-model.number="settings.ffmpeg.fps"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="0.01"
                step="0.01"
                :label="t('settings.frames.fps')"
            />
            <q-input
                v-model.number="settings.ffmpeg.fit_in_width"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="1"
                step="1"
                :label="t('settings.frames.width')"
            />
            <q-input
                v-model.number="settings.ffmpeg.fit_in_height"
                class="col-12 col-sm-6"
                outlined
                type="number"
                min="1"
                step="1"
                :label="t('settings.frames.height')"
            />
        </div>

        <q-separator />
        <frame-picker-settings v-model="settings.framePicker" embedded />
        <q-separator />

        <div class="text-subtitle1 text-weight-bold">{{ t('settings.colmap.title') }}</div>
        <div class="row q-col-gutter-md">
            <q-select
                v-model="settings.colmap.data_type"
                class="col-12 col-sm-6"
                outlined
                emit-value
                map-options
                :options="colmapDataTypeOptions"
                :label="t('settings.colmap.dataType')"
            />
            <q-select
                v-model="settings.colmap.quality"
                class="col-12 col-sm-6"
                outlined
                :options="colmapQualityOptions"
                emit-value
                map-options
                :label="t('settings.colmap.quality')"
            />
            <q-select
                v-model="settings.colmap.camera_model"
                class="col-12 col-sm-6"
                outlined
                :options="colmapCameraModelOptions"
                :label="t('settings.colmap.cameraModel')"
            />
        </div>
        <div class="row q-col-gutter-md">
            <q-toggle
                v-model="settings.colmap.single_camera"
                class="col-12 col-sm-6"
                :label="t('settings.colmap.sharedIntrinsics')"
            />
            <q-toggle
                v-model="settings.colmap.use_gpu"
                class="col-12 col-sm-6"
                :label="t('settings.colmap.useGpu')"
            />
            <q-toggle
                v-model="settings.colmap.use_global_mapper"
                class="col-12 col-sm-6"
                :label="t('settings.colmap.globalMapper')"
            />
        </div>

        <q-separator />
        <brush-settings v-model="settings.brush" embedded />
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import BrushSettings from 'src/components/BrushSettings.vue';
import FramePickerSettings from 'src/components/FramePickerSettings.vue';
import type { ReconstructionSettingsConfig } from 'src/lib/reconstruction-settings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const settings = defineModel<ReconstructionSettingsConfig>({ required: true });

const colmapDataTypeOptions = computed(() => [
    { label: t('settings.colmap.individual'), value: 'individual' },
    { label: t('settings.colmap.video'), value: 'video' },
    { label: t('settings.colmap.internet'), value: 'internet' },
]);
const colmapQualityOptions = computed(() => [
    { value: 'low', label: t('settings.colmap.qualities.low') },
    { value: 'medium', label: t('settings.colmap.qualities.medium') },
    { value: 'high', label: t('settings.colmap.qualities.high') },
    { value: 'extreme', label: t('settings.colmap.qualities.extreme') },
]);
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
