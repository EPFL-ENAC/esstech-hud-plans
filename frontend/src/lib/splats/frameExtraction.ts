export interface CommonExtractionConfig {
    fitInWidth: number;
    fitInHeight: number;
}

export interface FixedExtractionConfig extends CommonExtractionConfig {
    mode: 'fixed';
    fps: number;
}

export interface SmartExtractionConfig extends CommonExtractionConfig {
    mode: 'smart';
    min_fps: number;
    distance_threshold: number;
    outlier_sharpness_ratio: number;
}

export type FrameExtractionConfig = FixedExtractionConfig | SmartExtractionConfig;

export function makeDefaultFrameExtractionConfig(): FrameExtractionConfig {
    return {
        mode: 'fixed',
        fitInWidth: 1920,
        fitInHeight: 1920,
        fps: 2,
    };
}

/**
 * Helper to transition between modes while preserving common settings
 */
export function switchMode(
    current: FrameExtractionConfig,
    newMode: 'fixed' | 'smart',
): FrameExtractionConfig {
    const base = {
        fitInWidth: current.fitInWidth,
        fitInHeight: current.fitInHeight,
    };

    if (newMode === 'fixed') {
        return { ...base, mode: 'fixed', fps: 2 };
    } else {
        return {
            ...base,
            mode: 'smart',
            min_fps: 1,
            distance_threshold: 0.2,
            outlier_sharpness_ratio: 0.1,
        };
    }
}
