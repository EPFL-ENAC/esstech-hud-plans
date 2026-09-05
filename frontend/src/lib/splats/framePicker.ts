export interface FramePickerConfig {
    enabled: boolean;
    min_fps: number;
    distance_threshold: number;
    remove_outliers: boolean;
    outlier_sharpness_ratio: number;
}

export function makeDefaultFramePickerConfig(): FramePickerConfig {
    return {
        enabled: false,
        min_fps: 1,
        distance_threshold: 0.2,
        remove_outliers: true,
        outlier_sharpness_ratio: 0.1,
    };
}
