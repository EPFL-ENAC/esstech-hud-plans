<template>
    <q-form class="q-gutter-y-md" @submit="submit">
        <slot name="before" />

        <q-file v-model="videoFile" outlined accept="video/*" label="Video file" clearable>
            <template #prepend><q-icon name="movie" /></template>
        </q-file>

        <div class="text-subtitle1 text-weight-medium">ffmpeg settings</div>
        <div class="row q-col-gutter-md">
            <q-input
                v-model.number="settings.ffmpeg.fps"
                class="col-12 col-sm-4"
                outlined
                type="number"
                min="0.01"
                step="0.01"
                label="FPS"
            />
            <q-input
                v-model.number="settings.ffmpeg.fitInWidth"
                class="col-12 col-sm-4"
                outlined
                type="number"
                min="1"
                step="1"
                label="Fit-in width"
            />
            <q-input
                v-model.number="settings.ffmpeg.fitInHeight"
                class="col-12 col-sm-4"
                outlined
                type="number"
                min="1"
                step="1"
                label="Fit-in height"
            />
        </div>

        <q-separator />
        <frame-picker-settings v-model="framePickerConfig" />
        <q-separator />

        <div class="text-subtitle1 text-weight-medium">COLMAP settings</div>
        <div class="row q-col-gutter-md">
            <q-select
                v-model="settings.colmap.dataType"
                class="col-12 col-sm-4"
                outlined
                emit-value
                map-options
                :options="colmapDataTypeOptions"
                label="Data type"
            />
            <q-select
                v-model="settings.colmap.quality"
                class="col-12 col-sm-4"
                outlined
                :options="colmapQualityOptions"
                label="Quality"
            />
            <q-select
                v-model="settings.colmap.cameraModel"
                class="col-12 col-sm-4"
                outlined
                :options="colmapCameraModelOptions"
                label="Camera model"
            />
        </div>
        <div class="row q-col-gutter-md">
            <q-toggle
                v-model="settings.colmap.singleCamera"
                class="col-12 col-sm-4"
                label="Use shared camera intrinsics"
            />
            <q-toggle v-model="settings.colmap.useGpu" class="col-12 col-sm-4" label="Use GPU" />
            <q-toggle
                v-model="settings.colmap.useGlobalMapper"
                class="col-12 col-sm-4"
                label="Use global mapper"
            />
        </div>

        <q-separator />
        <brush-settings v-model="brushConfig" />

        <q-btn
            color="primary"
            icon="upload"
            :label="submitLabel"
            type="submit"
            :disable="!canSubmit || loading"
            :loading="loading"
        />
    </q-form>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import BrushSettings from 'src/components/BrushSettings.vue';
import FramePickerSettings from 'src/components/FramePickerSettings.vue';
import type { ColmapWorkflowSettings, ReconstructionSubmission } from 'src/lib/buildings';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from 'src/lib/splats/brush';
import { type FramePickerConfig, makeDefaultFramePickerConfig } from 'src/lib/splats/framePicker';

withDefaults(defineProps<{ loading?: boolean; submitLabel?: string }>(), {
    loading: false,
    submitLabel: 'Submit reconstruction',
});

const emit = defineEmits<{ submit: [submission: ReconstructionSubmission] }>();
const videoFile = ref<File | null>(null);
const framePickerConfig = ref<FramePickerConfig>(makeDefaultFramePickerConfig());
const brushConfig = ref<BrushTrainingConfig>(makeDefaultBrushConfig());
const settings = reactive({
    ffmpeg: { fps: 2, fitInWidth: 1920, fitInHeight: 1920 },
    colmap: {
        dataType: 'video' as ColmapWorkflowSettings['data_type'],
        quality: 'low' as ColmapWorkflowSettings['quality'],
        cameraModel: 'OPENCV' as ColmapWorkflowSettings['camera_model'],
        singleCamera: true,
        useGpu: false,
        useGlobalMapper: false,
    },
});

const colmapDataTypeOptions = [
    { label: 'Individual images', value: 'individual' },
    { label: 'Video frames', value: 'video' },
    { label: 'Internet images', value: 'internet' },
];
const colmapQualityOptions = ['low', 'medium', 'high', 'extreme'];
const colmapCameraModelOptions = ['PINHOLE', 'OPENCV', 'OPENCV_FISHEYE', 'RADIAL'];

const canSubmit = computed(
    () =>
        videoFile.value !== null &&
        settings.ffmpeg.fps > 0 &&
        settings.ffmpeg.fitInWidth > 0 &&
        settings.ffmpeg.fitInHeight > 0 &&
        (!framePickerConfig.value.enabled ||
            (framePickerConfig.value.min_fps > 0 &&
                framePickerConfig.value.distance_threshold >= 0 &&
                framePickerConfig.value.outlier_sharpness_ratio >= 0 &&
                framePickerConfig.value.outlier_sharpness_ratio <= 1)),
);

function submit(): void {
    if (!videoFile.value || !canSubmit.value) return;
    emit('submit', {
        video: videoFile.value,
        settings: {
            ffmpeg: {
                fps: settings.ffmpeg.fps,
                fit_in_width: settings.ffmpeg.fitInWidth,
                fit_in_height: settings.ffmpeg.fitInHeight,
            },
            frame_picker: framePickerConfig.value.enabled
                ? {
                      min_fps: framePickerConfig.value.min_fps,
                      distance_threshold: framePickerConfig.value.distance_threshold,
                      remove_outliers: framePickerConfig.value.remove_outliers,
                      outlier_sharpness_ratio: framePickerConfig.value.outlier_sharpness_ratio,
                  }
                : null,
            colmap: {
                data_type: settings.colmap.dataType,
                quality: settings.colmap.quality,
                camera_model: settings.colmap.cameraModel,
                single_camera: settings.colmap.singleCamera,
                use_gpu: settings.colmap.useGpu,
                use_global_mapper: settings.colmap.useGlobalMapper,
            },
            brush: {
                total_steps: brushConfig.value.totalSteps,
                render_mode: brushConfig.value.renderMode,
                sh_degree: brushConfig.value.shDegree,
                max_splats: brushConfig.value.maxSplats,
                refine_every: brushConfig.value.refineEvery,
                growth_grad_threshold: brushConfig.value.growthGradThreshold,
                growth_stop_iter: brushConfig.value.growthStopIter,
                max_resolution: brushConfig.value.maxResolution,
                subsample_frames: brushConfig.value.subsampleFrames,
                alpha_mode: brushConfig.value.alphaMode,
                export_every: brushConfig.value.exportEvery,
            },
        },
    });
}
</script>
