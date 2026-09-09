/**
 * Interactive blueprint viewer parameters.
 * Mirrors the backend model `InteractiveBlueprintParams` in
 * backend/api/models/splats.py. Keep both in sync.
 */
export interface BlueprintParams {
    viewerSize: number;
    sceneZRotation: number;
    displayCameraPositions: boolean;
    displayFloor: boolean;
    floorZOffset: number;
    cameramanHeightCm: number;
    sectionZFactor: { min: number; max: number } | null;
    densityThreshold: number;
    splatSizeMultiplier: number;
    opacityMultiplier: number;
    contrast: number;
}

export const DEFAULT_BLUEPRINT_PARAMS: BlueprintParams = {
    viewerSize: 700,
    sceneZRotation: 0,
    displayCameraPositions: true,
    displayFloor: false,
    floorZOffset: 0,
    cameramanHeightCm: 170,
    sectionZFactor: null,
    densityThreshold: 1.0,
    splatSizeMultiplier: 1.0,
    opacityMultiplier: 0.1,
    contrast: 2.0,
};
