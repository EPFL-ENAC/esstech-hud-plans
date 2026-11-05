import type {
    FfmpegSettings,
    SplatGenerationSettings,
    SpirulaGeometryWorkflowSettings,
    SpirulaSfmWorkflowSettings,
    SpirulaTrainWorkflowSettings,
} from './buildings';
import {
    type SpirulaGeometryConfig,
    type SpirulaSfmConfig,
    type SpirulaTrainConfig,
    makeDefaultSpirulaSfmConfig,
    makeDefaultSpirulaGeometryConfig,
    makeDefaultSpirulaTrainConfig,
} from './splats/spirula';
import { type FramePickerConfig, makeDefaultFramePickerConfig } from './splats/framePicker';

export type ReconstructionPreset = 'indoors' | 'outdoors' | 'advanced';

export interface ReconstructionSettingsConfig {
    ffmpeg: FfmpegSettings;
    framePicker: FramePickerConfig;
    spirulaSfm: SpirulaSfmConfig;
    spirulaGeometry: SpirulaGeometryConfig;
    spirulaTrain: SpirulaTrainConfig;
}

export function makeDefaultReconstructionSettings(
    preset: ReconstructionPreset = 'advanced',
): ReconstructionSettingsConfig {
    return {
        ffmpeg: { fps: preset === 'indoors' ? 4 : 2, fit_in_width: 1920, fit_in_height: 1920 },
        framePicker: makeDefaultFramePickerConfig(),
        spirulaSfm: makeDefaultSpirulaSfmConfig(preset),
        spirulaGeometry: makeDefaultSpirulaGeometryConfig(),
        spirulaTrain: makeDefaultSpirulaTrainConfig(),
    };
}

export function isValidReconstructionSettings(settings: ReconstructionSettingsConfig): boolean {
    const { ffmpeg, framePicker, spirulaTrain } = settings;
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
        positiveInteger(spirulaTrain.numIterations) &&
        Number.isInteger(spirulaTrain.shDegree) &&
        spirulaTrain.shDegree >= 0 &&
        spirulaTrain.shDegree <= 3 &&
        positiveInteger(spirulaTrain.capMax)
    );
}

export function toSplatGenerationSettings(
    settings: ReconstructionSettingsConfig,
): SplatGenerationSettings {
    const { framePicker, spirulaSfm, spirulaGeometry, spirulaTrain } = settings;

    const sfm: SpirulaSfmWorkflowSettings = {
        data_type: spirulaSfm.dataType,
        pairs: spirulaSfm.pairs,
        quality: spirulaSfm.quality,
        camera_model: spirulaSfm.cameraModel,
        single_camera: spirulaSfm.singleCamera,
    };
    const geometry: SpirulaGeometryWorkflowSettings = {
        compute_depth: spirulaGeometry.computeDepth,
        compute_normals: spirulaGeometry.computeNormals,
    };
    const train: SpirulaTrainWorkflowSettings = {
        num_iterations: spirulaTrain.numIterations,
        quality: spirulaTrain.quality,
        floater_suppression: spirulaTrain.floaterSuppression,
        meshing_preset: spirulaTrain.meshingPreset,
        primitive: spirulaTrain.primitive,
        sh_degree: spirulaTrain.shDegree,
        cap_max: spirulaTrain.capMax,
    };

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
        spirula_sfm: sfm,
        spirula_geometry: geometry,
        spirula_train: train,
    };
}
