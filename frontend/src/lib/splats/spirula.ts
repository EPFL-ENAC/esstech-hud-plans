export type SpirulaSfmDataType = 'individual' | 'video' | 'internet';
export type SpirulaSfmQuality = 'low' | 'medium' | 'high' | 'extreme';
export type SpirulaSfmCameraModel =
    'simple-pinhole' | 'pinhole' | 'radial' | 'opencv' | 'opencv-fisheye';

export interface SpirulaSfmConfig {
    dataType: SpirulaSfmDataType;
    quality: SpirulaSfmQuality;
    cameraModel: SpirulaSfmCameraModel;
    singleCamera: boolean;
}

export type SpirulaTrainQuality = 'low' | 'medium' | 'high' | 'ultra';
export type SpirulaTrainPrimitive = '3dgs' | 'mip';

export interface SpirulaTrainConfig {
    numIterations: number;
    quality: SpirulaTrainQuality;
    primitive: SpirulaTrainPrimitive;
    shDegree: number;
    capMax: number;
}

export function makeDefaultSpirulaSfmConfig(
    preset: 'indoors' | 'outdoors' | 'advanced',
): SpirulaSfmConfig {
    return {
        dataType: 'video',
        quality: preset === 'indoors' ? 'high' : 'low',
        cameraModel: 'opencv',
        singleCamera: true,
    };
}

export function makeDefaultSpirulaTrainConfig(): SpirulaTrainConfig {
    return {
        numIterations: 30_000,
        quality: 'medium',
        primitive: '3dgs',
        shDegree: 3,
        capMax: 1_000_000,
    };
}
