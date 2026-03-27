<script setup lang="ts">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SplatMesh } from '@sparkjsdev/spark';
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue';
import { useAsyncResultCollection } from 'unwrapped/vue';
import { AsyncResult } from 'unwrapped/core';
import { BlueprintGeometry, fetchBlueprintGeometryJSON } from 'src/lib/maths/blueprintGeometry';
import {
    autoDetectFloorOffset,
    type BlueprintSplatProcessingParams,
    generateBlueprintMesh,
} from 'src/lib/maths/blueprintMesh';
import { baseUrl } from 'boot/api';

const CAMERA_DISTANCE_FACTOR = 3.0;
const FLOOR_SIZE_FACTOR = 2; // times radius
const INITIAL_SECTION_HEIGHT_FACTOR = 1; // times radius
const SECTION_HEIGTHT_FACTOR_RANGE = 5;

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
const displayFloor = ref(false);

const floorZOffset = ref(0);
const averageCameraOffsetUnit = ref(1);
const averageCameraHeightUnit = computed(() => averageCameraOffsetUnit.value - floorZOffset.value);
const cameramanHeightCm = ref(170);
const cameraHeightCm = computed(() => cameramanHeightCm.value * 0.9); // Assume camera is at 90% of cameraman height
const cmPerUnit = computed(() => cameraHeightCm.value / averageCameraHeightUnit.value);

const sectionZFactor = ref({ min: -1, max: 1 });
const sectionZFactorStart = computed(() => -sectionZFactor.value.max);
const sectionZFactorEnd = computed(() => -sectionZFactor.value.min);
const densityThreshold = ref(1.0);
const opacityMultiplier = ref(0.2);
const opacityPower = ref(0.0);
const contrast = ref(2.0);

let geometryData: BlueprintGeometry | null = null;
const initialCameraPosition = ref<THREE.Vector3 | null>(null);
const initialCameraTarget = ref<THREE.Vector3 | null>(null);
const viewerSize = ref(700);
const thresholdEnabled = computed(() => !displayFloor.value);

const canvasFilter = computed(() => {
    if (!thresholdEnabled.value) {
        return 'none';
    }
    const brightness = 100;
    return `contrast(${100 * contrast.value}%) brightness(${brightness}%)`;
});

let paramsSaveTimeout: ReturnType<typeof setTimeout> | null = null;

async function saveBlueprintParams(): Promise<void> {
    const params = {
        viewerSize: viewerSize.value,
        sceneZRotation: sceneZRotation.value,
        displayCameraPositions: displayCameraPositions.value,
        displayFloor: displayFloor.value,
        floorZOffset: floorZOffset.value,
        cameramanHeightCm: cameramanHeightCm.value,
        sectionZFactor: sectionZFactor.value,
        densityThreshold: densityThreshold.value,
        opacityMultiplier: opacityMultiplier.value,
        contrast: contrast.value,
    };

    try {
        const response = await fetch(`${baseUrl}/splats/blueprint-params/${props.generationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(params),
        });
        if (!response.ok) {
            console.error('Failed to save blueprint parameters:', response.statusText);
        }
    } catch (error) {
        console.error('Failed to save blueprint parameters:', error);
    }
}

function scheduleParamsSave(): void {
    if (paramsSaveTimeout) {
        clearTimeout(paramsSaveTimeout);
    }
    paramsSaveTimeout = setTimeout(() => {
        void saveBlueprintParams();
    }, 500);
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

const collection = useAsyncResultCollection();

onMounted(() => {
    collection.value.add(
        'setup',
        AsyncResult.run(function* () {
            if (!container.value) {
                return;
            }

            const response = yield* AsyncResult.fromValuePromise(
                fetch(`${baseUrl}/splats/blueprint-params/${props.generationId}`),
            );
            const params = response.ok ? yield* AsyncResult.fromValuePromise(response.json()) : {};
            if (!response.ok) {
                console.error('Failed to load blueprint parameters:', response.statusText);
            }
            if (params.viewerSize) viewerSize.value = params.viewerSize;
            if (params.sceneZRotation !== undefined) sceneZRotation.value = params.sceneZRotation;
            if (params.displayCameraPositions !== undefined)
                displayCameraPositions.value = params.displayCameraPositions;
            if (params.displayFloor !== undefined) displayFloor.value = params.displayFloor;
            if (params.floorZOffset !== undefined) floorZOffset.value = params.floorZOffset;
            if (params.cameramanHeightCm) cameramanHeightCm.value = params.cameramanHeightCm;
            if (params.sectionZFactor) {
                sectionZFactor.value = params.sectionZFactor;
            }
            if (params.densityThreshold) densityThreshold.value = params.densityThreshold;
            if (params.opacityMultiplier) opacityMultiplier.value = params.opacityMultiplier;
            if (params.contrast) contrast.value = params.contrast;

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
                new THREE.CircleGeometry(geometryData.radius * FLOOR_SIZE_FACTOR, 64),
                new THREE.MeshBasicMaterial({
                    color: 0xddddff,
                    side: THREE.DoubleSide,
                    transparent: true,
                    opacity: 0.8,
                }),
            );
            floorPlaneMesh.visible = displayFloor.value;
            group.add(floorPlaneMesh);

            averageCameraOffsetUnit.value = geometryData.averageCameraZ;
            const cameraPositionsGeometry = new THREE.BufferGeometry().setFromPoints(
                geometryData.cameraPositions,
            );
            const cameraPositionsMaterial = new THREE.PointsMaterial({ color: 0xff0000, size: 3 });
            cameraPositionsPointsMesh = new THREE.Points(
                cameraPositionsGeometry,
                cameraPositionsMaterial,
            );
            cameraPositionsPointsMesh.setRotationFromMatrix(geometryData.worldRotationMatrix);
            group.add(cameraPositionsPointsMesh);
            sectionZFactor.value = {
                min: -INITIAL_SECTION_HEIGHT_FACTOR,
                max: INITIAL_SECTION_HEIGHT_FACTOR,
            };

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
        }),
    );
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
    scheduleParamsSave();
});

watch(
    [densityThreshold, opacityMultiplier, opacityPower, sectionZFactorStart, sectionZFactorEnd],
    () => {
        collection.value.add(`generation-${Date.now()}`, generateBlueprint());
        scheduleParamsSave();
    },
);

watch(sceneZRotation, () => scheduleParamsSave());
watch(displayCameraPositions, () => scheduleParamsSave());
watch(displayFloor, () => scheduleParamsSave());
watch(floorZOffset, () => scheduleParamsSave());
watch(cameramanHeightCm, () => scheduleParamsSave());
watch(contrast, () => scheduleParamsSave());

function generateBlueprint(onFinishedLoading?: (mesh: SplatMesh) => void): AsyncResult<SplatMesh> {
    return AsyncResult.run(function* () {
        const params: BlueprintSplatProcessingParams = {
            densityThreshold: densityThreshold.value * geometryData!.radius ** 3,
            opacityMultiplier: opacityMultiplier.value,
            opacityPower: opacityPower.value,
            sectionZStart:
                averageCameraOffsetUnit.value + sectionZFactorStart.value * geometryData!.radius,
            sectionZEnd:
                averageCameraOffsetUnit.value + sectionZFactorEnd.value * geometryData!.radius,
        };

        mesh = yield* AsyncResult.fromValuePromise(
            generateBlueprintMesh(props.splatData, params, onFinishedLoading),
        );

        mesh.setRotationFromMatrix(geometryData!.worldRotationMatrix);
        mesh.position.set(
            -geometryData!.center.x,
            -geometryData!.center.y,
            -geometryData!.center.z,
        );

        group.children.forEach((child) => {
            if (child instanceof SplatMesh) {
                group.remove(child);
            }
        });
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
        <q-card class="toolbar-card q-mb-lg">
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
                                <div class="text-caption text-grey-7">
                                    Blueprint tilt: {{ sceneZRotation }}°
                                </div>
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
                        <div class="text-overline text-primary q-mb-sm row items-center">
                            Floor Height & Scale
                            <q-icon name="info" size="16px" class="q-ml-xs cursor-pointer">
                                <q-tooltip max-width="250px">
                                    Adjust the average camera height and the floor level to allow
                                    estimation of real-world dimensions.
                                </q-tooltip>
                            </q-icon>
                        </div>

                        <div class="row q-col-gutter-sm">
                            <div class="col-6">
                                <div class="text-caption text-grey-7">Cameraman height (cm)</div>
                                <q-slider
                                    v-model="cameramanHeightCm"
                                    :min="100"
                                    :max="200"
                                    dense
                                    label
                                    :label-value="cameramanHeightCm.toFixed(0)"
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

                        <div class="q-mt-md">
                            <q-toggle
                                v-model="displayFloor"
                                label="Show Floor"
                                color="primary"
                                dense
                                :disable="collection.anyLoading()"
                            />
                        </div>
                    </div>

                    <q-separator vertical inset />

                    <!-- Section 3: Splat Processing & Clipping -->
                    <div class="section-splat q-px-md">
                        <div class="text-overline text-primary q-mb-sm">Splat Processing</div>

                        <div class="splat-processing">
                            <div class="control-group section-z-range">
                                <div class="text-caption text-grey-7">
                                    Section limits (bottom - top)
                                    <q-icon name="info" size="16px" class="cursor-pointer">
                                        <q-tooltip max-width="250px">
                                            Only display the splats within these vertical limits.
                                        </q-tooltip>
                                    </q-icon>
                                </div>
                                <q-range
                                    v-model="sectionZFactor"
                                    :min="-SECTION_HEIGTHT_FACTOR_RANGE"
                                    :max="SECTION_HEIGTHT_FACTOR_RANGE"
                                    :step="0.01"
                                    label
                                    :left-label-value="sectionZFactor.min.toFixed(2)"
                                    :right-label-value="sectionZFactor.max.toFixed(2)"
                                />
                            </div>

                            <div class="control-group opacity-threshold">
                                <div class="text-caption text-grey-7">
                                    Density Threshold
                                    <q-icon name="info" size="16px" class="cursor-pointer">
                                        <q-tooltip max-width="250px">
                                            Increase this value to hide splats that are less opaque
                                            or too large.
                                        </q-tooltip>
                                    </q-icon>
                                </div>
                                <q-slider
                                    v-model="densityThreshold"
                                    :min="0.01"
                                    :max="20.0"
                                    :step="0.01"
                                    label
                                    :label-value="densityThreshold.toFixed(2)"
                                />
                            </div>

                            <div class="control-group opacity-multiplier">
                                <div class="text-caption text-grey-7">
                                    Opacity Multiplier
                                    <q-icon name="info" size="16px" class="cursor-pointer">
                                        <q-tooltip max-width="250px">
                                            Control the darkness of the splats.
                                        </q-tooltip>
                                    </q-icon>
                                </div>
                                <q-slider
                                    v-model="opacityMultiplier"
                                    :min="0.001"
                                    :max="2.0"
                                    :step="0.001"
                                    label
                                    :label-value="opacityMultiplier.toFixed(2)"
                                />
                            </div>
                            <div class="control-group contrast">
                                <div class="text-caption text-grey-7">
                                    Contrast
                                    <q-icon name="info" size="16px" class="cursor-pointer">
                                        <q-tooltip max-width="250px">
                                            Increase this value to increase contrast. Disable "Show
                                            floor" to enable this option.
                                        </q-tooltip>
                                    </q-icon>
                                </div>
                                <q-slider
                                    v-model="contrast"
                                    :min="1"
                                    :max="10"
                                    :step="0.01"
                                    label
                                    :label-value="contrast.toFixed(2)"
                                    :disable="displayFloor"
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
            class="canvas-container shadow-4"
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
        'section-z-range section-z-range'
        'opacity-threshold opacity-threshold'
        'opacity-multiplier contrast';
}

.section-z-range {
    grid-area: section-z-range;
}

.opacity-multiplier {
    grid-area: opacity-multiplier;
}

.contrast {
    grid-area: contrast;
}

.viewer-container {
    display: flex;
    flex-direction: column;
    align-items: center;
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
    background: rgba(0, 0, 0, 0.2);
    color: white;
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
