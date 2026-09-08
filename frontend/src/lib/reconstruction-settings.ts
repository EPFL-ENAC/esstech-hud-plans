import type { ColmapWorkflowSettings, FfmpegSettings, SplatGenerationSettings } from './buildings';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from './splats/brush';
import { type FramePickerConfig, makeDefaultFramePickerConfig } from './splats/framePicker';

export type ReconstructionPreset = 'indoors' | 'outdoors' | 'advanced';

export interface ReconstructionSettingsConfig {
    ffmpeg: FfmpegSettings;
    framePicker: FramePickerConfig;
    colmap: ColmapWorkflowSettings;
    brush: BrushTrainingConfig;
}

export function makeDefaultReconstructionSettings(): ReconstructionSettingsConfig {
    return {
        ffmpeg: { fps: 2, fit_in_width: 1920, fit_in_height: 1920 },
        framePicker: makeDefaultFramePickerConfig(),
        colmap: {
            data_type: 'video',
            quality: 'low',
            camera_model: 'OPENCV',
            single_camera: true,
            use_gpu: false,
            use_global_mapper: false,
        },
        brush: makeDefaultBrushConfig(),
    };
}

export function isValidReconstructionSettings(settings: ReconstructionSettingsConfig): boolean {
    const { ffmpeg, framePicker, brush } = settings;
    const positiveInteger = (value: number) => Number.isInteger(value) && value > 0;
    const positiveNumber = (value: number) => Number.isFinite(value) && value > 0;
    return (
        positiveNumber(ffmpeg.fps) &&
        positiveInteger(ffmpeg.fit_in_width) &&
        positiveInteger(ffmpeg.fit_in_height) &&
        (!framePicker.enabled ||
            (positiveInteger(framePicker.min_fps) &&
                Number.isFinite(framePicker.distance_threshold) &&
                framePicker.distance_threshold >= 0 &&
                Number.isFinite(framePicker.outlier_sharpness_ratio) &&
                framePicker.outlier_sharpness_ratio >= 0 &&
                framePicker.outlier_sharpness_ratio <= 1)) &&
        positiveInteger(brush.totalSteps) &&
        Number.isInteger(brush.shDegree) &&
        brush.shDegree >= 0 &&
        brush.shDegree <= 3 &&
        positiveInteger(brush.maxSplats) &&
        positiveInteger(brush.refineEvery) &&
        positiveNumber(brush.growthGradThreshold) &&
        Number.isInteger(brush.growthStopIter) &&
        brush.growthStopIter >= 0 &&
        positiveInteger(brush.maxResolution) &&
        positiveInteger(brush.subsampleFrames) &&
        positiveInteger(brush.exportEvery)
    );
}

export function toSplatGenerationSettings(
    settings: ReconstructionSettingsConfig,
): SplatGenerationSettings {
    const { framePicker, brush } = settings;
    return {
        ffmpeg: { ...settings.ffmpeg },
        frame_picker: framePicker.enabled
            ? {
                  min_fps: framePicker.min_fps,
                  distance_threshold: framePicker.distance_threshold,
                  remove_outliers: framePicker.remove_outliers,
                  outlier_sharpness_ratio: framePicker.outlier_sharpness_ratio,
              }
            : null,
        colmap: { ...settings.colmap },
        brush: {
            total_steps: brush.totalSteps,
            render_mode: brush.renderMode,
            sh_degree: brush.shDegree,
            max_splats: brush.maxSplats,
            refine_every: brush.refineEvery,
            growth_grad_threshold: brush.growthGradThreshold,
            growth_stop_iter: brush.growthStopIter,
            max_resolution: brush.maxResolution,
            subsample_frames: brush.subsampleFrames,
            alpha_mode: brush.alphaMode,
            export_every: brush.exportEvery,
        },
    };
}
