export type RenderMode = 'default' | 'mip';
export type AlphaMode = 'masked' | 'transparent';

export interface BrushTrainingConfig {
    // Core Training
    totalSteps: number;
    renderMode: RenderMode;
    shDegree: number;

    // Refinement (Growth/Density)
    maxSplats: number;
    refineEvery: number;
    growthGradThreshold: number;
    growthStopIter: number;

    // Dataset/Resolution
    maxResolution: number;
    subsampleFrames: number;
    alphaMode: AlphaMode;

    // Exports
    exportEvery: number;
}

export function makeDefaultBrushConfig(): BrushTrainingConfig {
    return {
        totalSteps: 10_000,
        renderMode: 'default',
        shDegree: 3,
        maxSplats: 10_000_000,
        refineEvery: 200,
        growthGradThreshold: 0.0025,
        growthStopIter: 15_000,
        maxResolution: 1920,
        subsampleFrames: 1,
        alphaMode: 'transparent',
        exportEvery: 5_000,
    };
}
