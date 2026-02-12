<script setup lang="ts">
import * as THREE from "three";
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SplatMesh } from "@sparkjsdev/spark";
import { computed, onMounted, ref, useTemplateRef, watch } from "vue";


const CAMERA_DISTANCE_FACTOR = 3.0;


interface BlueprintGeometry {
    world_rotation: number[][];
    center: number[];
    radius: number;
}

const props = defineProps<{
    splatData: ArrayBuffer;
    generationId: string;
}>();

const container = useTemplateRef<HTMLDivElement>("container");
let controls: OrbitControls | null = null;
let mesh: SplatMesh | null = null;
let camera: THREE.OrthographicCamera | null = null;
let scene: THREE.Scene | null = null;
let renderer: THREE.WebGLRenderer | null = null;

const opacityMultiplier = ref(0.2);
const clipPlanes = ref(1.0);
const geometryData = ref<BlueprintGeometry | null>(null);
const initialCameraPosition = ref<THREE.Vector3 | null>(null);
const initialCameraTarget = ref<THREE.Vector3 | null>(null);
const isLoading = ref(true);
const error = ref<string | null>(null);

const thresholdEnabled = ref(false);

const canvasFilter = computed(() => {
    if (!thresholdEnabled.value) {
        return 'none';
    }
    const brightness = 100;
    const contrast = 10000;
    return `contrast(${contrast}%) brightness(${brightness}%)`;
});

async function fetchBlueprintGeometry(): Promise<void> {
    try {
        const response = await fetch(`http://localhost:8000/splats/blueprint-geometry/${props.generationId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch blueprint geometry: ${response.statusText}`);
        }
        geometryData.value = await response.json();
    } catch (e) {
        error.value = e instanceof Error ? e.message : 'Unknown error';
        isLoading.value = false;
    }
}


function resetView(): void {
    if (controls && initialCameraPosition.value && initialCameraTarget.value) {
        camera?.position.copy(initialCameraPosition.value);
        controls.target.copy(initialCameraTarget.value);
        controls.update();
    }
}


onMounted(async () => {
    await fetchBlueprintGeometry();

    if (!geometryData.value || !container.value) {
        return;
    }

    const { world_rotation, center, radius } = geometryData.value;

    scene = new THREE.Scene();

    const frustumSize = radius * 4;
    camera = new THREE.OrthographicCamera(
        -frustumSize / 2,
        frustumSize / 2,
        frustumSize / 2,
        -frustumSize / 2,
        0.1,
        radius * 10
    );
    camera.position.set(0, 0, radius * CAMERA_DISTANCE_FACTOR);
    camera.lookAt(0, 0, 0);

    initialCameraPosition.value = camera.position.clone();
    initialCameraTarget.value = new THREE.Vector3(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(700, 700);
    renderer.setClearColor(0xffffff, 1);
    container.value.appendChild(renderer.domElement);

    const clonedBuffer = props.splatData.slice(0);
    mesh = new SplatMesh({ fileBytes: clonedBuffer });
    mesh.recolor = new THREE.Color(0x000000);

    const rotationMatrix = new THREE.Matrix4();
    rotationMatrix.set(
        world_rotation[0]![0]!, world_rotation[1]![0]!, world_rotation[2]![0]!, 0,
        world_rotation[0]![1]!, world_rotation[1]![1]!, world_rotation[2]![1]!, 0,
        world_rotation[0]![2]!, world_rotation[1]![2]!, world_rotation[2]![2]!, 0,
        0, 0, 0, 1
    );
    mesh.setRotationFromMatrix(rotationMatrix);
    mesh.position.set(-center[0]!, -center[1]!, -center[2]!);
    scene.add(mesh);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(initialCameraTarget.value);
    controls.enableRotate = true;
    controls.update();

    renderer.setAnimationLoop(() => {
        controls?.update();

        if (mesh) {
            mesh.opacity = opacityMultiplier.value;
        }

        if (renderer && scene && camera) {
            renderer.render(scene, camera);
        }
    });

    isLoading.value = false;
});

watch(clipPlanes, (newValue) => {
    if (camera && geometryData.value) {
        const { radius } = geometryData.value;
        const centerDistance = radius * CAMERA_DISTANCE_FACTOR;
        const clipOffset = radius * newValue;
        camera.near = Math.max(0.1, centerDistance - clipOffset);
        camera.far = centerDistance + clipOffset;
        camera.updateProjectionMatrix();
    }
});
</script>

<template>
    <div class="viewer-container">
        <div ref="container" class="canvas-container" :style="{ filter: canvasFilter }">
            <div v-if="isLoading" class="loading-overlay">
                <q-spinner color="primary" size="3em" />
                <div class="q-mt-sm">Loading interactive blueprint...</div>
            </div>
            <div v-if="error" class="error-overlay">
                <q-icon name="error" color="negative" size="3em" />
                <div class="q-mt-sm text-negative">{{ error }}</div>
            </div>
        </div>

        <div class="controls-container q-pa-md">
            <div class="row q-gutter-md items-center">
                <q-btn
                    label="Reset View"
                    color="primary"
                    @click="resetView"
                    :disable="isLoading || !!error"
                />

                <div class="control-group">
                    <div class="text-caption text-grey-7">Clip Planes</div>
                    <q-slider
                        v-model="clipPlanes"
                        :min="0.01"
                        :max="2.0"
                        :step="0.01"
                        label
                        :label-value="clipPlanes.toFixed(1)"
                        style="width: 200px"
                        :disable="isLoading || !!error"
                    />
                </div>

                <div class="control-group">
                    <div class="text-caption text-grey-7">Opacity</div>
                    <q-slider
                        v-model="opacityMultiplier"
                        :min="0.001"
                        :max="1.0"
                        :step="0.001"
                        label
                        :label-value="opacityMultiplier.toFixed(2)"
                        style="width: 200px"
                        :disable="isLoading || !!error"
                    />
                </div>

                <q-separator vertical class="q-mx-sm" />

                <div class="control-group">
                    <q-checkbox
                        v-model="thresholdEnabled"
                        label="Binary Threshold"
                        :disable="isLoading || !!error"
                    />
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.viewer-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
}

.canvas-container {
    width: 700px;
    height: 700px;
    border: 1px solid #ccc;
    position: relative;
    background: #000;
}

.loading-overlay,
.error-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.8);
    color: white;
}

.controls-container {
    width: 100%;
    max-width: 700px;
}

.control-group {
    display: flex;
    flex-direction: column;
}
</style>
