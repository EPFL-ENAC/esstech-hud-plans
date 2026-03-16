import { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import type { BlueprintGeometry } from './blueprintGeometry';
import { Histogram } from './histogram';

export interface BlueprintSplatProcessingParams {
    sectionZStart: number;
    sectionZEnd: number;
    densityThreshold: number;
    opacityMultiplier: number;
    opacityPower: number;
}

export async function generateBlueprintMesh(
    splat: ArrayBuffer,
    params: BlueprintSplatProcessingParams,
    onFinishedLoading?: (mesh: SplatMesh) => void,
): Promise<SplatMesh> {
    return new Promise((resolve) => {
        const black = new THREE.Color(0x000000);
        const clonedBuffer = splat.slice(0);

        new SplatMesh({
            fileBytes: clonedBuffer,
            onLoad(mesh) {
                mesh.packedSplats.forEachSplat((index, center, scales, quaternion, opacity) => {
                    const FIXED_OPACITY = 0.3;
                    const volume = scales.x * scales.y * scales.z;
                    const density = opacity / volume;
                    let newOpacity = 0;
                    if (
                        density >= params.densityThreshold &&
                        center.y >= params.sectionZStart &&
                        center.y <= params.sectionZEnd
                    ) {
                        newOpacity =
                            ((params.opacityMultiplier * opacity) / FIXED_OPACITY) **
                                (10 ** params.opacityPower) *
                            FIXED_OPACITY;
                    }

                    mesh.packedSplats.setSplat(
                        index,
                        center,
                        scales,
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
