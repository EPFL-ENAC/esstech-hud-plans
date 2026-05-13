export type CameraType = 'standard' | 'wide_angle' | 'zoom';

export interface InputConfig {
    type: 'video' | 'colmap';
    selectedVideoFile: File | null;
    colmapGenerationId?: string;
    colmapSparseReconstructionId?: number;
    deviceName: string;
    cameraType: CameraType;
}

export function makeDefaultInputConfig(): InputConfig {
    return {
        type: 'video',
        selectedVideoFile: null,
        deviceName: '',
        cameraType: 'standard',
    };
}
