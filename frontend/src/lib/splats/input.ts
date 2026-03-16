export interface InputConfig {
    type: 'video' | 'colmap';
    selectedVideoFile: File | null;
    colmapGenerationId?: string;
}

export function makeDefaultInputConfig(): InputConfig {
    return {
        type: 'video',
        selectedVideoFile: null,
    };
}
