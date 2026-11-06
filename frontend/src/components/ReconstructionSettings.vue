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

        <div class="text-subtitle1 text-weight-bold">{{ t('settings.spirula.sfm.title') }}</div>
        <div class="row q-col-gutter-md">
            <q-select
                v-model="settings.spirulaSfm.dataType"
                class="col-12 col-sm-6"
                outlined
                emit-value
                map-options
                :options="sfmDataTypeOptions"
                :label="t('settings.spirula.sfm.dataType')"
            />
            <q-select
                v-model="settings.spirulaSfm.pairs"
                class="col-12 col-sm-6"
                outlined
                emit-value
                map-options
                :options="sfmPairsOptions"
                :label="t('settings.spirula.sfm.pairs')"
            />
            <q-select
                v-model="settings.spirulaSfm.quality"
                class="col-12 col-sm-6"
                outlined
                :options="sfmQualityOptions"
                emit-value
                map-options
                :label="t('settings.spirula.sfm.quality')"
            />
            <q-select
                v-model="settings.spirulaSfm.cameraModel"
                class="col-12 col-sm-6"
                outlined
                :options="sfmCameraModelOptions"
                emit-value
                map-options
                :label="t('settings.spirula.sfm.cameraModel')"
            />
            <q-toggle
                v-model="settings.spirulaSfm.singleCamera"
                class="col-12 col-sm-6"
                :label="t('settings.spirula.sfm.sharedIntrinsics')"
            />
        </div>

        <q-separator />
        <div class="text-subtitle1 text-weight-bold">
            {{ t('settings.spirula.geometry.title') }}
        </div>
        <div class="row q-col-gutter-md">
            <q-toggle
                v-model="settings.spirulaGeometry.computeDepth"
                class="col-12 col-sm-6"
                :label="t('settings.spirula.geometry.computeDepth')"
            />
            <q-toggle
                v-model="settings.spirulaGeometry.computeNormals"
                class="col-12 col-sm-6"
                :label="t('settings.spirula.geometry.computeNormals')"
            />
        </div>

        <q-separator />
        <spirula-train-settings v-model="settings.spirulaTrain" embedded />
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import SpirulaTrainSettings from 'src/components/SpirulaTrainSettings.vue';
import FramePickerSettings from 'src/components/FramePickerSettings.vue';
import type { ReconstructionSettingsConfig } from 'src/lib/reconstruction-settings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const settings = defineModel<ReconstructionSettingsConfig>({ required: true });

const sfmDataTypeOptions = computed(() => [
    { label: t('settings.spirula.sfm.individual'), value: 'individual' },
    { label: t('settings.spirula.sfm.video'), value: 'video' },
    { label: t('settings.spirula.sfm.internet'), value: 'internet' },
]);
const sfmPairsOptions = computed(() => [
    { value: 'auto', label: t('settings.spirula.sfm.pairsAuto') },
    { value: 'exhaustive', label: t('settings.spirula.sfm.pairsExhaustive') },
    { value: 'sequential', label: t('settings.spirula.sfm.pairsSequential') },
    { value: 'prefilter', label: t('settings.spirula.sfm.pairsPrefilter') },
]);
const sfmQualityOptions = computed(() => [
    { value: 'low', label: t('settings.spirula.sfm.qualities.low') },
    { value: 'medium', label: t('settings.spirula.sfm.qualities.medium') },
    { value: 'high', label: t('settings.spirula.sfm.qualities.high') },
    { value: 'extreme', label: t('settings.spirula.sfm.qualities.extreme') },
]);
const sfmCameraModelOptions = computed(() => [
    { value: 'simple-pinhole', label: t('settings.spirula.sfm.cameraModels.simplePinhole') },
    { value: 'pinhole', label: t('settings.spirula.sfm.cameraModels.pinhole') },
    { value: 'radial', label: t('settings.spirula.sfm.cameraModels.radial') },
    { value: 'opencv', label: t('settings.spirula.sfm.cameraModels.opencv') },
    { value: 'opencv-fisheye', label: t('settings.spirula.sfm.cameraModels.opencvFisheye') },
]);
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
