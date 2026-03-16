import { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import type { BlueprintGeometry } from './blueprintGeometry';
import { Histogram } from './histogram';

export interface BlueprintSplatProcessingParams {
    sectionZStart: number;
    sectionZEnd: number;
    opacityThreshold: number;
    densityThreshold: number;
    opacityMultiplier: number;
    opacityPower: number;
    opacityGain: number;
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
                    // const volume = scales.x * scales.y * scales.z;
                    const projectedArea = scales.x * scales.z;
                    const powedOpacity = Math.pow(opacity, 5);
                    const density = projectedArea > 0 ? powedOpacity / projectedArea : 0;

                    let newOpacity = 0;
                    if (center.y >= params.sectionZStart && center.y <= params.sectionZEnd) {
                        if (
                            opacity >= params.opacityThreshold &&
                            density >= params.densityThreshold
                        ) {
                            newOpacity =
                                Math.pow(opacity * params.opacityMultiplier, params.opacityPower) *
                                params.opacityGain;
                        }
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
