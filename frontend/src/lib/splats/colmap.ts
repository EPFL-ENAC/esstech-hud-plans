export type ColmapDataType = 'individual' | 'video' | 'internet';
export type ColmapQuality = 'low' | 'medium' | 'high' | 'extreme';
export type ColmapCameraModel = 'PINHOLE' | 'OPENCV' | 'OPENCV_FISHEYE' | 'RADIAL';

export interface AutoReconstructorConfig {
    data_type: ColmapDataType;
    quality: ColmapQuality;
    camera_model: ColmapCameraModel;
    max_image_size: number;
    single_camera: boolean;
    dense: boolean;
}

export interface ManualPipelineConfig {
    camera_model: ColmapCameraModel;
    max_num_features: number;
    overlap: number;
    loop_closure: boolean;
    min_track_len: number;
    use_gpu: boolean;
}

// Discriminated Union for the Submit event
export type ColmapSubmitPayload =
    | { mode: 'auto'; data: AutoReconstructorConfig }
    | { mode: 'manual'; data: ManualPipelineConfig };

// Union for the v-model
export type ColmapConfig = AutoReconstructorConfig | ManualPipelineConfig;

export const dataTypes = [
    { value: 'individual', label: 'Individual Images', desc: 'Collection of separate photos.' },
    { value: 'video', label: 'Video', desc: 'Frames coming from a single video source.' },
    { value: 'internet', label: 'Internet Images', desc: 'Images sourced from online platforms.' },
];

export const qualityOptions = [
    { value: 'low', label: 'Low', desc: 'Fastest processing, minimal feature points.' },
    { value: 'medium', label: 'Medium', desc: 'Balanced speed and reconstruction detail.' },
    { value: 'high', label: 'High', desc: 'Slow, high density of points for complex scenes.' },
    { value: 'extreme', label: 'Extreme', desc: 'Very slow; uses maximum image resolution.' },
];

export const cameraModels = [
    { value: 'PINHOLE', label: 'Pinhole', desc: 'Standard camera with no lens distortion.' },
    {
        value: 'OPENCV',
        label: 'OpenCV',
        desc: 'Standard lens with distortion (best for most phones).',
    },
    { value: 'OPENCV_FISHEYE', label: 'Fisheye', desc: 'Wide-angle or GoPro style lenses.' },
    { value: 'RADIAL', label: 'Radial', desc: 'Simple distortion model for older/basic lenses.' },
];

export function makeAutoDefaults(): AutoReconstructorConfig {
    return {
        data_type: 'individual',
        quality: 'medium',
        camera_model: 'OPENCV',
        max_image_size: 2000,
        single_camera: true,
        dense: false,
    };
}

export function makeManualDefaults(): ManualPipelineConfig {
    return {
        camera_model: 'OPENCV',
        max_num_features: 8192,
        overlap: 10,
        loop_closure: true,
        min_track_len: 2,
        use_gpu: true,
    };
}
