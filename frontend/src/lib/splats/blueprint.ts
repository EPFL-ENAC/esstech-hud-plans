export interface BlueprintConfig {
    imageWidth: number;
    imageHeight: number;
    radiusScale: number;
    verticalClip: number;
    opacityShift: number;
    opacity: number;
}

export function makeDefaultBlueprintConfig(): BlueprintConfig {
    return {
        imageWidth: 2048,
        imageHeight: 2048,
        radiusScale: 2.0,
        verticalClip: 0.2,
        opacityShift: -0.5,
        opacity: 0.05,
    }
}
