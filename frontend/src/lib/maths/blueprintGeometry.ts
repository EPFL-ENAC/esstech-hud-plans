import * as THREE from 'three';
import { AsyncResult } from 'unwrapped/core';
import { baseUrl } from 'boot/api';

export interface BlueprintGeometryResponse {
    world_rotation: number[][];
    center: number[];
    radius: number;
    positions: number[][];
}

export class BlueprintGeometry {
    private rotationMatrix = new THREE.Matrix4();

    constructor(protected readonly response: BlueprintGeometryResponse) {
        this.rotationMatrix.set(
            response.world_rotation[0]![0]!,
            response.world_rotation[1]![0]!,
            response.world_rotation[2]![0]!,
            0,
            response.world_rotation[0]![1]!,
            response.world_rotation[1]![1]!,
            response.world_rotation[2]![1]!,
            0,
            response.world_rotation[0]![2]!,
            response.world_rotation[1]![2]!,
            response.world_rotation[2]![2]!,
            0,
            0,
            0,
            0,
            1,
        );
    }

    get cameraPositionsRaw() {
        return this.response.positions;
    }

    get cameraPositions() {
        return this.response.positions.map((pos) => new THREE.Vector3(pos[0], pos[1], pos[2]));
    }

    get averageCameraZ() {
        const positions = this.cameraPositions;
        if (positions.length === 0) return 0;

        let sumZ = 0;
        for (const pos of positions) {
            sumZ += pos.z;
        }
        return sumZ / positions.length;
    }

    get worldRotationMatrix() {
        return this.rotationMatrix;
    }

    get center() {
        return new THREE.Vector3(this.response.center[0], this.response.center[1], this.response.center[2]);
    }

    get radius() {
        return this.response.radius;
    }
}

export function fetchBlueprintGeometryJSON(id: string): AsyncResult<BlueprintGeometryResponse> {
    return AsyncResult.run(function* () {
        const response = yield* AsyncResult.fromValuePromise(fetch(
            `${baseUrl}/splats/blueprint-geometry/${id}`,
        ));
        if (!response.ok) {
            return yield* AsyncResult.errTag('fetch_blueprint_geometry_failed', `Failed to fetch blueprint geometry: ${response.statusText}`);
        }
        return yield* AsyncResult.fromValuePromise(response.json());
    });
}
