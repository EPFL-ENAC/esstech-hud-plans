export type SpirulaSfmDataType = 'individual' | 'video' | 'internet';
export type SpirulaSfmPairs = 'auto' | 'exhaustive' | 'sequential' | 'prefilter';
export type SpirulaSfmQuality = 'low' | 'medium' | 'high' | 'extreme';
export type SpirulaSfmCameraModel =
    | 'simple-pinhole'
    | 'pinhole'
    | 'radial'
    | 'opencv'
    | 'opencv-fisheye';

export interface SpirulaObjectPromptsConfig {
    enabled: boolean;
    prompts: string[];
}

export interface SpirulaSfmConfig {
    dataType: SpirulaSfmDataType;
    pairs: SpirulaSfmPairs;
    quality: SpirulaSfmQuality;
    cameraModel: SpirulaSfmCameraModel;
    singleCamera: boolean;
    removeObjects: SpirulaObjectPromptsConfig;
}

export interface SpirulaGeometryConfig {
    computeDepth: boolean;
    computeNormals: boolean;
}

export type SpirulaTrainQuality = 'low' | 'medium' | 'high' | 'ultra';
export type SpirulaTrainPrimitive = '3dgs' | 'mip';

export interface SpirulaTrainConfig {
    numIterations: number;
    quality: SpirulaTrainQuality;
    floaterSuppression: boolean;
    meshingPreset: boolean;
    primitive: SpirulaTrainPrimitive;
    shDegree: number;
    capMax: number;
    keepObjects: SpirulaObjectPromptsConfig;
}

export const DEFAULT_REMOVE_OBJECT_PROMPTS = ['person'];
export const DEFAULT_KEEP_OBJECT_PROMPTS = ['walls', 'doors', 'windows', 'floor', 'ceiling'];

export function makeDefaultSpirulaSfmConfig(
    preset: 'indoors' | 'outdoors' | 'advanced',
): SpirulaSfmConfig {
    return {
        dataType: 'video',
        pairs: 'exhaustive',
        quality: preset === 'outdoors' ? 'medium' : 'high',
        cameraModel: 'opencv',
        singleCamera: true,
        removeObjects: { enabled: false, prompts: [...DEFAULT_REMOVE_OBJECT_PROMPTS] },
    };
}

export function makeDefaultSpirulaGeometryConfig(): SpirulaGeometryConfig {
    return {
        computeDepth: false,
        computeNormals: true,
    };
}

export function makeDefaultSpirulaTrainConfig(): SpirulaTrainConfig {
    return {
        numIterations: 30_000,
        quality: 'medium',
        floaterSuppression: true,
        meshingPreset: false,
        primitive: '3dgs',
        shDegree: 3,
        capMax: 1_000_000,
        keepObjects: { enabled: false, prompts: [...DEFAULT_KEEP_OBJECT_PROMPTS] },
    };
}
