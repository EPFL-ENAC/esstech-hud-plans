<script setup lang="ts">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { SplatMesh } from '@sparkjsdev/spark';
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue';
import { useAsyncResultCollection } from 'unwrapped/vue';
import { AsyncResult } from 'unwrapped/core';
import { BlueprintGeometry, fetchBlueprintGeometryJSON } from 'src/lib/maths/blueprintGeometry';
import { autoDetectFloorOffset, type BlueprintSplatProcessingParams, generateBlueprintMesh } from 'src/lib/maths/blueprintMesh';

const CAMERA_DISTANCE_FACTOR = 3.0;

const props = defineProps<{
    splatData: ArrayBuffer;
    generationId: string;
}>();

const container = useTemplateRef<HTMLDivElement>('container');
let controls: OrbitControls | null = null;
let camera: THREE.OrthographicCamera | null = null;
let scene: THREE.Scene | null = null;
let renderer: THREE.WebGLRenderer | null = null;
const group = new THREE.Group();
let mesh: SplatMesh | null = null;
let floorPlaneMesh: THREE.Mesh | null = null;
let cameraPositionsPointsMesh: THREE.Points | null = null;

const scaleBarWidthPx = ref(0);
const sceneZRotation = ref(0);
const displayCameraPositions = ref(true);
const displayFloor = ref(true);

const floorZOffset = ref(0);
const averageCameraOffsetUnit = ref(1);
const averageCameraHeightUnit = computed(() => averageCameraOffsetUnit.value - floorZOffset.value);
const cameramanHeightCm = ref(180);
const cameraHeightCm = computed(() => cameramanHeightCm.value * 0.9); // Assume camera is at 90% of cameraman height
const cmPerUnit = computed(() => cameraHeightCm.value / averageCameraHeightUnit.value);

const sectionZStart = ref(0);
const sectionZEnd = ref(10);
const densityThreshold = ref(0.01);
const opacityThreshold = ref(0);
const opacityMultiplier = ref(0.2);
const opacityPower = ref(4.0);
const opacityGain = ref(100.0);

let geometryData: BlueprintGeometry | null = null;
const initialCameraPosition = ref<THREE.Vector3 | null>(null);
const initialCameraTarget = ref<THREE.Vector3 | null>(null);
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

const collection = useAsyncResultCollection();

onMounted(() => {
    collection.value.add('setup', AsyncResult.run(function* () {
        if (!container.value) {
            return;
        }

        const geometryJSON = yield* fetchBlueprintGeometryJSON(props.generationId);
        geometryData = new BlueprintGeometry(geometryJSON);

        scene = new THREE.Scene();
        scene.add(group);

        const frustumSize = geometryData.radius * 4;
        camera = new THREE.OrthographicCamera(
            -frustumSize / 2,
            frustumSize / 2,
            frustumSize / 2,
            -frustumSize / 2,
            0.1,
            geometryData.radius * 10,
        );
        camera.position.set(0, 0, geometryData.radius * CAMERA_DISTANCE_FACTOR);
        camera.lookAt(0, 0, 0);

        floorPlaneMesh = new THREE.Mesh(
            new THREE.PlaneGeometry(geometryData.radius * 10, geometryData.radius * 10),
            new THREE.MeshBasicMaterial({
                color: 0xeeeeee,
                side: THREE.DoubleSide,
                transparent: true,
                opacity: 0.9,
            }),
        );
        group.add(floorPlaneMesh);

        averageCameraOffsetUnit.value = geometryData.averageCameraZ;
        const cameraPositionsGeometry = new THREE.BufferGeometry().setFromPoints(geometryData.cameraPositions);
        const cameraPositionsMaterial = new THREE.PointsMaterial({ color: 0xff0000, size: 3 });
        cameraPositionsPointsMesh = new THREE.Points(cameraPositionsGeometry, cameraPositionsMaterial);
        cameraPositionsPointsMesh.setRotationFromMatrix(geometryData.worldRotationMatrix);
        group.add(cameraPositionsPointsMesh);
        sectionZStart.value = averageCameraOffsetUnit.value - 0.5;
        sectionZEnd.value = averageCameraOffsetUnit.value + 0.5;

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
        controls.addEventListener('change', updateScaleOverlay);
        updateScaleOverlay();

        yield* generateBlueprint((mesh) => {
            if (!geometryData) return;

            floorZOffset.value = autoDetectFloorOffset(mesh, geometryData) ?? 0;
        });

        renderer.setAnimationLoop(() => {
            controls?.update();

            if (renderer && scene && camera) {
                renderer.render(scene, camera);
            }
        });
    }));
});

watch(viewerSize, (newSize) => {
    if (renderer) {
        renderer.setSize(newSize, newSize);
    }
    if (camera && geometryData) {
        const radius = geometryData.radius;
        const frustumSize = radius * 4;
        camera.left = -frustumSize / 2;
        camera.right = frustumSize / 2;
        camera.top = frustumSize / 2;
        camera.bottom = -frustumSize / 2;
        camera.updateProjectionMatrix();
    }
    updateScaleOverlay();
});

watch(
    [opacityMultiplier, opacityPower, opacityGain, opacityThreshold, densityThreshold, sectionZStart, sectionZEnd],
    () => collection.value.add(`generation-${Date.now()}`, generateBlueprint()),
);

function generateBlueprint(onFinishedLoading?: (mesh: SplatMesh) => void): AsyncResult<SplatMesh> {
    return AsyncResult.run(function* () {
        if (mesh) {
            group.remove(mesh);
        }

        const params: BlueprintSplatProcessingParams = {
            opacityMultiplier: opacityMultiplier.value,
            opacityPower: opacityPower.value,
            opacityGain: opacityGain.value,
            opacityThreshold: opacityThreshold.value,
            densityThreshold: densityThreshold.value,
            sectionZStart: sectionZStart.value,
            sectionZEnd: sectionZEnd.value,
        };

        mesh = yield* AsyncResult.fromValuePromise(generateBlueprintMesh(props.splatData, params, onFinishedLoading));

        mesh.setRotationFromMatrix(geometryData!.worldRotationMatrix);
        mesh.position.set(-geometryData!.center.x, -geometryData!.center.y, -geometryData!.center.z);

        group.add(mesh);

        return mesh;
    });
}

watch(floorZOffset, (newOffset) => {
    if (floorPlaneMesh) {
        floorPlaneMesh.position.z = newOffset;
    }
});

watch(displayFloor, (show) => {
    if (floorPlaneMesh) {
        floorPlaneMesh.visible = show;
    }
});

watch(cmPerUnit, () => {
    updateScaleOverlay();
});

function updateScaleOverlay(): void {
    if (!renderer || !camera || !container.value) return;
    // CSS pixel width of the canvas in the layout
    const canvas = renderer.domElement;
    const canvasWidthPx = canvas.clientWidth || viewerSize.value;

    // 1 meter in "scene units"
    const unitsPerMeter = 100 / cmPerUnit.value;

    // Ortho visible width in world units depends on zoom
    const visibleWorldWidthUnits = (camera.right - camera.left) / camera.zoom;
    const pxPerUnit = canvasWidthPx / visibleWorldWidthUnits;

    scaleBarWidthPx.value = unitsPerMeter * pxPerUnit;
}

watch(displayCameraPositions, (show) => {
    if (cameraPositionsPointsMesh) {
        cameraPositionsPointsMesh.visible = show;
    }
});

watch(sceneZRotation, (tilt) => {
    group.rotateZ(THREE.MathUtils.degToRad(tilt) - group.rotation.z);
});
</script>

<template>
    <div class="viewer-container q-pa-md">
        <!-- Main Control Toolbar -->
        <q-card class="toolbar-card q-mb-lg shadow-2">
            <q-card-section class="q-py-md">
                <div class="toolbar-grid">
                    <!-- Section 1: Viewer Settings -->
                    <div class="section-viewer q-px-md">
                        <div class="text-overline text-primary q-mb-sm">Viewer Settings</div>
                        <div class="column q-gutter-sm">
                            <q-btn
                                label="Reset View"
                                color="primary"
                                icon="refresh"
                                unelevated
                                dense
                                @click="resetView"
                                :disable="collection.anyLoading()"
                            />
                            <div>
                                <div class="text-caption text-grey-7">Size: {{ viewerSize }}px</div>
                                <q-slider
                                    v-model="viewerSize"
                                    :min="300"
                                    :max="1200"
                                    :step="50"
                                    dense
                                />
                            </div>
                            <div>
                                <div class="text-caption text-grey-7">Blueprint tilt: {{ sceneZRotation }}°</div>
                                <q-slider
                                    v-model="sceneZRotation"
                                    :min="-90"
                                    :max="90"
                                    :step="1"
                                    dense
                                />
                            </div>
                            <div>
                                <q-toggle
                                    v-model="displayCameraPositions"
                                    label="Show Camera Positions"
                                    color="primary"
                                    dense
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div>
                                <q-toggle
                                    v-model="displayFloor"
                                    label="Show Floor"
                                    color="primary"
                                    dense
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <q-btn
                                label="Save Image"
                                color="positive"
                                icon="save"
                                outline
                                dense
                                @click="exportImage"
                                :disable="collection.anyLoading()"
                            />
                        </div>
                    </div>

                    <q-separator vertical inset />

                    <!-- Section 2: Floor Height & Scale -->
                    <div class="section-floor q-px-md">
                        <div class="text-overline text-primary q-mb-sm">Floor Height & Scale</div>
                        <div class="row q-col-gutter-sm">
                            <div class="col-6">
                                <div class="text-caption text-grey-7">Cameraman height (cm)</div>
                                <q-slider
                                    v-model="cameramanHeightCm"
                                    :min="100"
                                    :max="200"
                                    dense
                                    label
                                    :label-value="cameramanHeightCm.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="col-6">
                                <div class="text-caption text-grey-7">Floor Offset</div>
                                <q-slider
                                    v-model="floorZOffset"
                                    :min="-10"
                                    :max="10"
                                    :step="0.1"
                                    dense
                                    label
                                    :label-value="floorZOffset.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                        </div>

                        <div class="info-grid q-mt-sm">
                            <div class="info-item">
                                <span class="label">Camera Height:</span>
                                <span class="value">{{ cameraHeightCm.toFixed(2) }} cm</span>
                            </div>
                            <div class="info-item">
                                <span class="label">Scale:</span>
                                <span class="value text-caption"
                                    >{{ cmPerUnit.toFixed(4) }} cm/u</span
                                >
                            </div>
                        </div>
                    </div>

                    <q-separator vertical inset />

                    <!-- Section 3: Splat Processing & Clipping -->
                    <div class="section-splat q-px-md">
                        <div class="text-overline text-primary q-mb-sm">Splat Processing</div>
                        <div class="splat-processing">
                            <div class="control-group section-z-start">
                                <div class="text-caption text-grey-7">Section Start</div>
                                <q-slider
                                    v-model="sectionZStart"
                                    :min="-10.0"
                                    :max="10.0"
                                    :step="0.01"
                                    label
                                    :label-value="sectionZStart.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="control-group section-z-end">
                                <div class="text-caption text-grey-7">Section End</div>
                                <q-slider
                                    v-model="sectionZEnd"
                                    :min="-10.0"
                                    :max="10.0"
                                    :step="0.01"
                                    label
                                    :label-value="sectionZEnd.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>

                            <div class="control-group density-threshold">
                                <div class="text-caption text-grey-7">Density Threshold</div>
                                <q-slider
                                    v-model="densityThreshold"
                                    :min="0.001"
                                    :max="100.0"
                                    :step="0.001"
                                    label
                                    :label-value="densityThreshold.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="control-group opacity-threshold">
                                <div class="text-caption text-grey-7">Opacity Threshold</div>
                                <q-slider
                                    v-model="opacityThreshold"
                                    :min="0.001"
                                    :max="1.0"
                                    :step="0.001"
                                    label
                                    :label-value="opacityThreshold.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="control-group opacity-multiplier">
                                <div class="text-caption text-grey-7">Opacity Multiplier</div>
                                <q-slider
                                    v-model="opacityMultiplier"
                                    :min="0.001"
                                    :max="1.0"
                                    :step="0.001"
                                    label
                                    :label-value="opacityMultiplier.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="control-group opacity-power">
                                <div class="text-caption text-grey-7">Opacity Power</div>
                                <q-slider
                                    v-model="opacityPower"
                                    :min="0.1"
                                    :max="10.0"
                                    :step="0.1"
                                    label
                                    :label-value="opacityPower.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                            <div class="control-group opacity-gain">
                                <div class="text-caption text-grey-7">Opacity Gain</div>
                                <q-slider
                                    v-model="opacityGain"
                                    :min="0.1"
                                    :max="500.0"
                                    :step="0.1"
                                    label
                                    :label-value="opacityGain.toFixed(2)"
                                    :disable="collection.anyLoading()"
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </q-card-section>
        </q-card>

        <!-- Canvas Container -->
        <div
            ref="container"
            class="canvas-container shadow-8"
            :style="{
                filter: canvasFilter,
                width: `${viewerSize}px`,
                height: `${viewerSize}px`,
                maxWidth: '95vw',
            }"
        >
            <div class="scale-overlay" aria-label="Scale: 1 meter">
                <div class="scale-bar" :style="{ width: `${scaleBarWidthPx}px` }" />
                <div class="scale-text">1 m</div>
            </div>
            <div v-if="collection.anyLoading()" class="loading-overlay">
                <q-spinner-grid color="primary" size="4em" />
                <div class="q-mt-md text-h6">Processing Blueprint...</div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.splat-processing {
    display: grid;
    gap: 1rem 0.5rem;

    grid-template-areas:
        'section-z-start section-z-end'
        'density-threshold density-threshold'
        'opacity-threshold opacity-multiplier'
        'opacity-power opacity-gain';
}

.section-z-start {
    grid-area: section-z-start;
}

.section-z-end {
    grid-area: section-z-end;
}

.density-threshold {
    grid-area: density-threshold;
}

.opacity-threshold {
    grid-area: opacity-threshold;
}

.opacity-multiplier {
    grid-area: opacity-multiplier;
}

.opacity-power {
    grid-area: opacity-power;
}

.opacity-gain {
    grid-area: opacity-gain;
}

.viewer-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    background-color: #f4f7f9;
    min-height: 100vh;
}

.toolbar-card {
    width: 100%;
    max-width: 1100px;
    border-radius: 12px;
    background: white;
}

.toolbar-grid {
    display: grid;
    grid-template-columns: 3fr auto 4fr auto 5fr;
    align-items: stretch;
}

.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    background: #f0f4f8;
    padding: 8px;
    border-radius: 6px;
    border: 1px solid #dbe3eb;
}

.info-item {
    display: flex;
    flex-direction: column;
}

.info-item .label {
    font-size: 0.65rem;
    text-transform: uppercase;
    color: #78909c;
    font-weight: bold;
}

.info-item .value {
    font-size: 0.9rem;
    font-weight: 600;
    color: #2c3e50;
}

.canvas-container {
    border: 4px solid #1a1a1a;
    position: relative;
    background: #000;
    border-radius: 8px;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.loading-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.9);
    color: white;
    backdrop-filter: blur(4px);
    z-index: 20;
}


.scale-overlay {
    position: absolute;
    left: 12px;
    bottom: 12px;
    z-index: 30;
    pointer-events: none; /* don't block OrbitControls */
    background: rgba(255, 255, 255, 0.85);
    color: #111;
    border: 1px solid rgba(0, 0, 0, 0.25);
    border-radius: 6px;
    padding: 8px 10px;
    display: grid;
    gap: 6px;
}

.scale-bar {
    height: 6px;
    background: #00aa00;
    border: 1px solid rgba(0, 0, 0, 0.4);
    border-radius: 2px;
}

.scale-text {
    font-size: 12px;
    font-weight: 600;
    line-height: 1;
}
</style>
