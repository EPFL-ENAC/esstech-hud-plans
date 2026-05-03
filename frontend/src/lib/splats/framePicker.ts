export interface FramePickerConfig {
    enabled: boolean;
    sharpness_threshold: number;
    distance_threshold: number;
    max_bin_length: number;
    grid_cols: number;
    grid_rows: number;
}

export function makeDefaultFramePickerConfig(): FramePickerConfig {
    return {
        enabled: false,
        sharpness_threshold: 0.5,
        distance_threshold: 0.2,
        max_bin_length: 10,
        grid_cols: 8,
        grid_rows: 8,
    };
}
