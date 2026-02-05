export type RenderMode = "default" | "mip";
export type AlphaMode = "masked" | "transparent";


// Options with descriptions
export const renderModeOptions = [
    { value: 'default', label: 'Default', desc: 'Standard rasterization; fastest performance.' },
    { value: 'mip', label: 'Mip', desc: 'Anti-aliased rendering; reduces flickering on small details.' }
];

export const alphaModeOptions = [
    { value: 'transparent', label: 'Transparent', desc: 'Uses alpha channel for semi-transparency (glass, smoke).' },
    { value: 'masked', label: 'Masked', desc: 'Binary visibility; treats alpha as a hard cutout.' }
];

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
        totalSteps: 30_000,
        renderMode: "default",
        shDegree: 3,
        maxSplats: 10_000_000,
        refineEvery: 200,
        growthGradThreshold: 0.003,
        growthStopIter: 15_000,
        maxResolution: 1920,
        subsampleFrames: 1,
        alphaMode: "transparent",
        exportEvery: 5_000,
    }
}