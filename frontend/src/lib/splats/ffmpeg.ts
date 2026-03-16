export interface FFMPEGExtractionConfig {
    fps: number;
    fitInWidth: number;
    fitInHeight: number;
}

export function makeDefaultFFMPEGConfig(): FFMPEGExtractionConfig {
    return {
        fps: 2,
        fitInWidth: 1920,
        fitInHeight: 1920,
    };
}
