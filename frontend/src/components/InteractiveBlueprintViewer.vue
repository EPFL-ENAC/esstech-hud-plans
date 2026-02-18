<script setup lang="ts">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SplatMesh } from '@sparkjsdev/spark';
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue';

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

const container = useTemplateRef<HTMLDivElement>('container');
let controls: OrbitControls | null = null;
let mesh: SplatMesh | null = null;
let camera: THREE.OrthographicCamera | null = null;
let scene: THREE.Scene | null = null;
let renderer: THREE.WebGLRenderer | null = null;


const densityThreshold = ref(0.01);
const opacityThreshold = ref(0);
const opacityMultiplier = ref(0.2);
const opacityPower = ref(4.0);
const opacityGain = ref(100.0);

const clipNear = ref(0.5);
const clipFar = ref(2.0);
const geometryData = ref<BlueprintGeometry | null>(null);
const initialCameraPosition = ref<THREE.Vector3 | null>(null);
const initialCameraTarget = ref<THREE.Vector3 | null>(null);
const isLoading = ref(true);
const error = ref<string | null>(null);
const viewerSize = ref(700);

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
        const response = await fetch(
            `http://localhost:8000/splats/blueprint-geometry/${props.generationId}`,
        );
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

function exportImage(): void {
    if (!renderer || !container.value) return;

    const canvas = container.value.querySelector('canvas');
    if (!canvas) return;

    const link = document.createElement('a');
    link.download = `blueprint-${props.generationId}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
}

const rotationMatrix = new THREE.Matrix4();
const center = new THREE.Vector3();

onMounted(async () => {
    await fetchBlueprintGeometry();

    if (!geometryData.value || !container.value) {
        return;
    }

    const { world_rotation, center: centerCoords, radius } = geometryData.value;
    rotationMatrix.set(
        world_rotation[0]![0]!,
        world_rotation[1]![0]!,
        world_rotation[2]![0]!,
        0,
        world_rotation[0]![1]!,
        world_rotation[1]![1]!,
        world_rotation[2]![1]!,
        0,
        world_rotation[0]![2]!,
        world_rotation[1]![2]!,
        world_rotation[2]![2]!,
        0,
        0,
        0,
        0,
        1,
    );
    center.set(centerCoords[0]!, centerCoords[1]!, centerCoords[2]!);

    scene = new THREE.Scene();

    const frustumSize = radius * 4;
    camera = new THREE.OrthographicCamera(
        -frustumSize / 2,
        frustumSize / 2,
        frustumSize / 2,
        -frustumSize / 2,
        0.1,
        radius * 10,
    );
    camera.position.set(0, 0, radius * CAMERA_DISTANCE_FACTOR);
    camera.lookAt(0, 0, 0);

    initialCameraPosition.value = camera.position.clone();
    initialCameraTarget.value = new THREE.Vector3(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(viewerSize.value, viewerSize.value);
    renderer.setClearColor(0xffffff, 1);
    container.value.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(initialCameraTarget.value);
    controls.enableRotate = true;
    controls.update();

    renderer.setAnimationLoop(() => {
        controls?.update();

        if (renderer && scene && camera) {
            renderer.render(scene, camera);
        }
    });

    isLoading.value = false;
});

watch(viewerSize, (newSize) => {
    if (renderer) {
        renderer.setSize(newSize, newSize);
    }
    if (camera && geometryData.value) {
        const { radius } = geometryData.value;
        const frustumSize = radius * 4;
        camera.left = -frustumSize / 2;
        camera.right = frustumSize / 2;
        camera.top = frustumSize / 2;
        camera.bottom = -frustumSize / 2;
        camera.updateProjectionMatrix();
    }
});

watch([clipNear, clipFar], ([newNear, newFar]) => {
    if (!camera || !geometryData.value) return;

    const { radius } = geometryData.value;
    const centerDistance = radius * CAMERA_DISTANCE_FACTOR;

    // Near plane: distance minus offset 
    // (Smaller slider value = further from camera = tighter clip)
    camera.near = Math.max(0.1, centerDistance - (radius * newNear));

    // Far plane: distance plus offset
    camera.far = centerDistance + (radius * newFar);

    camera.updateProjectionMatrix();
});

watch([opacityMultiplier, opacityPower, opacityGain, opacityThreshold, densityThreshold], ([newMultiplier, newPower, newGain, newThreshold, newDensityThreshold]) => {
    if (mesh) {
        scene?.remove(mesh);
    }

    const black = new THREE.Color(0x000000);
    const clonedBuffer = props.splatData.slice(0);
    let maxDensity = 0;
    let minDensity = Infinity;
    mesh = new SplatMesh({
        fileBytes: clonedBuffer,
        onLoad(mesh) {
            mesh.packedSplats.forEachSplat((index, center, scales, quaternion, opacity) => {
                const volume = scales.x * scales.y * scales.z;
                const opacityPower = Math.pow(opacity, 10);
                const density = volume > 0 ? opacityPower / volume : 0;
                maxDensity = Math.max(maxDensity, density);
                minDensity = Math.min(minDensity, density);

                let newOpacity = 0;
                if (opacity >= newThreshold && density >= newDensityThreshold) {
                    newOpacity = Math.pow(opacity * newMultiplier, newPower) * newGain;
                }
                mesh.packedSplats.setSplat(index, center, scales, quaternion, newOpacity, black);
            });
            console.log(`Density range: ${minDensity} - ${maxDensity}`);
        },
    });

    // mesh.recolor = new THREE.Color(0x000000);
    mesh.setRotationFromMatrix(rotationMatrix);
    mesh.position.set(-center.x, -center.y, -center.z);

    scene?.add(mesh);
}, { immediate: true });
</script>

<template>
    <div class="viewer-container">
        <div class="controls-container q-pa-md">
            <div class="row q-gutter-md items-center">
                <q-btn label="Reset View" color="primary" @click="resetView" :disable="isLoading || !!error" />

                <div class="control-group">
                    <div class="text-caption text-grey-7">Size</div>
                    <q-slider v-model="viewerSize" :min="300" :max="1200" :step="50" label
                        :label-value="`${viewerSize}px`" style="width: 150px" :disable="isLoading || !!error" />
                </div>

                <div class="control-group">
                    <div class="text-caption text-grey-7">Clip Near</div>
                    <q-slider v-model="clipNear" :min="0.01" :max="2.0" :step="0.01" label
                        :label-value="clipNear.toFixed(1)" style="width: 150px" :disable="isLoading || !!error" />
                </div>
                <div class="control-group">
                    <div class="text-caption text-grey-7">Clip Far</div>
                    <q-slider v-model="clipFar" :min="0.01" :max="2.0" :step="0.01" label
                        :label-value="clipFar.toFixed(1)" style="width: 150px" :disable="isLoading || !!error" />
                </div>

                <div class="control-group">
                    <div class="text-caption text-grey-7">Density Threshold</div>
                    <q-slider
                        v-model="densityThreshold"
                        :min="0.001"
                        :max="100.0"
                        :step="0.001"
                        label
                        :label-value="densityThreshold.toFixed(2)"
                        style="width: 150px"
                        :disable="isLoading || !!error"
                    />
                </div>
                <div class="control-group">
                    <div class="text-caption text-grey-7">Opacity Threshold</div>
                    <q-slider
                        v-model="opacityThreshold"
                        :min="0.001"
                        :max="1.0"
                        :step="0.001"
                        label
                        :label-value="opacityThreshold.toFixed(2)"
                        style="width: 150px"
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
                        style="width: 150px"
                        :disable="isLoading || !!error"
                    />
                </div>
                <div class="control-group">
                    <div class="text-caption text-grey-7">Opacity Power</div>
                    <q-slider
                        v-model="opacityPower"
                        :min="0.1"
                        :max="10.0"
                        :step="0.1"
                        label
                        :label-value="opacityPower.toFixed(1)"
                        style="width: 150px"
                        :disable="isLoading || !!error"
                    />
                </div>
                <div class="control-group">
                    <div class="text-caption text-grey-7">Opacity Gain</div>
                    <q-slider
                        v-model="opacityGain"
                        :min="0.1"
                        :max="500.0"
                        :step="0.1"
                        label
                        :label-value="opacityGain.toFixed(1)"
                        style="width: 150px"
                        :disable="isLoading || !!error"
                    />
                </div>

                <q-separator vertical class="q-mx-sm" />

                <div class="control-group">
                    <q-checkbox v-model="thresholdEnabled" label="Binary Threshold" :disable="isLoading || !!error" />
                </div>

                <q-separator vertical class="q-mx-sm" />

                <q-btn label="Save as Image" color="positive" icon="save" @click="exportImage"
                    :disable="isLoading || !!error" />
            </div>
        </div>

        <div ref="container" class="canvas-container"
            :style="{ filter: canvasFilter, width: `${viewerSize}px`, height: `${viewerSize}px` }">
            <div v-if="isLoading" class="loading-overlay">
                <q-spinner color="primary" size="3em" />
                <div class="q-mt-sm">Loading interactive blueprint...</div>
            </div>
            <div v-if="error" class="error-overlay">
                <q-icon name="error" color="negative" size="3em" />
                <div class="q-mt-sm text-negative">{{ error }}</div>
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
