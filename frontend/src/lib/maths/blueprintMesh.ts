import { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import type { BlueprintGeometry } from './blueprintGeometry';
import { Histogram } from './histogram';

export interface BlueprintSplatProcessingParams {
    sectionZStart: number;
    sectionZEnd: number;
    densityThreshold: number;
    splatSizeMultiplier: number;
    opacityMultiplier: number;
    opacityPower: number;
    worldRotationMatrix?: THREE.Matrix4;
    center?: THREE.Vector3;
}

export async function generateBlueprintMesh(
    splat: ArrayBuffer,
    params: BlueprintSplatProcessingParams,
    onFinishedLoading?: (mesh: SplatMesh) => void,
): Promise<SplatMesh> {
    return new Promise((resolve) => {
        const black = new THREE.Color(0x000000);
        const clonedBuffer = splat.slice(0);
        const hasRotation = params.worldRotationMatrix && params.center;
        const rotationMatrix = params.worldRotationMatrix;
        const center = params.center;
        const p = new THREE.Vector3();

        new SplatMesh({
            fileBytes: clonedBuffer,
            onLoad(mesh) {
                mesh.packedSplats.forEachSplat((index, centerRaw, scales, quaternion, opacity) => {
                    const FIXED_OPACITY = 0.3;
                    const volume = scales.x * scales.y * scales.z;
                    const density = opacity / volume;
                    let newOpacity = 0;

                    let sectionZ: number;
                    if (hasRotation && rotationMatrix && center) {
                        p.set(
                            centerRaw.x - center.x,
                            centerRaw.y - center.y,
                            centerRaw.z - center.z,
                        );
                        p.applyMatrix4(rotationMatrix);
                        sectionZ = p.z;
                    } else {
                        sectionZ = centerRaw.y;
                    }

                    if (
                        density >= params.densityThreshold &&
                        -sectionZ >= params.sectionZStart &&
                        -sectionZ <= params.sectionZEnd
                    ) {
                        newOpacity =
                            ((params.opacityMultiplier * opacity) / FIXED_OPACITY) **
                                (10 ** params.opacityPower) *
                            FIXED_OPACITY;
                    }

                    const scaledScales = new THREE.Vector3(
                        scales.x * params.splatSizeMultiplier,
                        scales.y * params.splatSizeMultiplier,
                        scales.z * params.splatSizeMultiplier,
                    );

                    mesh.packedSplats.setSplat(
                        index,
                        centerRaw,
                        scaledScales,
                        quaternion,
                        newOpacity,
                        black,
                    );
                });

                onFinishedLoading?.(mesh);

                resolve(mesh);
            },
        });
    });
}

export function autoDetectFloorOffset(
    mesh: SplatMesh,
    geometryData: BlueprintGeometry,
): number | null {
    const zValues = new Float64Array(mesh.packedSplats.numSplats);

    const p = new THREE.Vector3();
    mesh.packedSplats.forEachSplat((index, center) => {
        p.set(
            center.x - geometryData.center.x,
            center.y - geometryData.center.y,
            center.z - geometryData.center.z,
        );
        p.applyMatrix4(geometryData.worldRotationMatrix);
        zValues[index] = p.z;
    });

    const zValuesHistogram = new Histogram(zValues, 300);
    const biggestBin = zValuesHistogram.getHighestBin();
    if (biggestBin) {
        return (biggestBin.binStart + biggestBin.binEnd) / 2;
    }

    return null;
}
