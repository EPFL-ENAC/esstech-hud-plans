<script setup lang="ts">
import * as THREE from 'three';
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useAsyncResultCollection } from 'unwrapped/vue';
import { AsyncResult } from 'unwrapped/core';
import type { ReconstructionPointCloudMeta } from 'src/lib/buildings';
import type { ZAxisRange } from 'src/lib/maths/zDistribution';
import PlanPointDensityBar from 'src/components/PlanPointDensityBar.vue';

const PAN_MARGIN = 0.2;
const FIT_MARGIN = 1.1;
const ZOOM_OUT_FACTOR = 0.5;
const ZOOM_IN_FACTOR = 40;
const ROTATE_SPEED = 0.01;
const WHEEL_ZOOM_SPEED = 0.001;
const POINT_SIZE_MIN = 0.1;
const POINT_SIZE_MAX = 2;
const POINT_SIZE_STEP = 0.1;
const POINT_OPACITY_MIN = 0.01;
const POINT_OPACITY_MAX = 0.5;
const POINT_OPACITY_STEP = 0.01;
const DEFAULT_POINT_SIZE = 0.5;
const DEFAULT_POINT_OPACITY = 0.15;
const FIXED_VIEWER_SIZE = 700;
const MIN_SPAN = 1e-6;
/** Clip plane constant that keeps every point; the plane count must stay fixed. */
const CLIP_OPEN = 1e6;

const DEFAULT_BOUNDS: ReconstructionPointCloudMeta['bounds'] = [
    [-1, -1, -1],
    [1, 1, 1],
];

const props = defineProps<{
    buffer: ArrayBuffer;
    meta: ReconstructionPointCloudMeta | null;
    reconstructionId: string;
    /** Fill the available space instead of a fixed square viewer size. */
    fill?: boolean;
}>();

const { t } = useI18n();

const container = useTemplateRef<HTMLDivElement>('container');
let renderer: THREE.WebGLRenderer | null = null;
let camera: THREE.OrthographicCamera | null = null;
let scene: THREE.Scene | null = null;
let points: THREE.Points | null = null;
let geometry: THREE.BufferGeometry | null = null;
let material: THREE.PointsMaterial | null = null;
const group = new THREE.Group();

// Points outside the selected height range are discarded on the GPU. The group only
// rotates around Z and translates in X/Y, so local Z is world Z here; transform the
// planes by group.matrixWorld if that ever changes.
const minPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), CLIP_OPEN);
const maxPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), CLIP_OPEN);
const clipPlanes = [minPlane, maxPlane];
const zRange = ref<ZAxisRange | null>(null);

let resizeObserver: ResizeObserver | null = null;
let bounds: ReconstructionPointCloudMeta['bounds'] = DEFAULT_BOUNDS;
let frustumSize = 2;
let fitZoom = 1;
const view = { targetX: 0, targetY: 0, rotation: 0, zoom: 1 };

interface PointerState {
    x: number;
    y: number;
    button: number;
}

interface PinchState {
    distance: number;
    angle: number;
    zoom: number;
    rotation: number;
}

const activePointers = new Map<number, PointerState>();
let pinch: PinchState | null = null;

function readStoredValue(key: string, fallback: number, min: number, max: number): number {
    const raw = window.localStorage.getItem(key);
    const value = raw === null ? Number.NaN : Number(raw);
    return Number.isFinite(value) ? THREE.MathUtils.clamp(value, min, max) : fallback;
}

const decimalsForStep = (step: number) => String(step).split('.')[1]?.length ?? 0;
const formatValue = (value: number, step: number) => value.toFixed(decimalsForStep(step));

const pointSize = ref(
    readStoredValue(
        `plan-point-size:${props.reconstructionId}`,
        DEFAULT_POINT_SIZE,
        POINT_SIZE_MIN,
        POINT_SIZE_MAX,
    ),
);
const pointOpacity = ref(
    readStoredValue(
        `plan-point-opacity:${props.reconstructionId}`,
        DEFAULT_POINT_OPACITY,
        POINT_OPACITY_MIN,
        POINT_OPACITY_MAX,
    ),
);
const scaleBarWidthPx = ref(0);
const hasScale = computed(() => {
    const cmPerUnit = props.meta?.cm_per_unit;
    return cmPerUnit != null && cmPerUnit > 0;
});

function boundsFromBuffer(buffer: ArrayBuffer): ReconstructionPointCloudMeta['bounds'] | null {
    const positions = new Float32Array(buffer);
    if (positions.length < 3) return null;
    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    for (let i = 0; i + 2 < positions.length; i += 3) {
        const x = positions[i]!;
        const y = positions[i + 1]!;
        const z = positions[i + 2]!;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        minZ = Math.min(minZ, z);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        maxZ = Math.max(maxZ, z);
    }
    return [
        [minX, minY, minZ],
        [maxX, maxY, maxZ],
    ];
}

function resolveBounds(): ReconstructionPointCloudMeta['bounds'] {
    return props.meta?.bounds ?? boundsFromBuffer(props.buffer) ?? DEFAULT_BOUNDS;
}

function applyBoundsAndCamera(): void {
    if (!camera) return;
    bounds = resolveBounds();
    const [[minX, minY, minZ], [maxX, maxY, maxZ]] = bounds;
    const spanX = Math.max(maxX - minX, MIN_SPAN);
    const spanY = Math.max(maxY - minY, MIN_SPAN);
    const depth = Math.max(maxZ - minZ, MIN_SPAN);
    frustumSize = Math.max(spanX, spanY);
    const distance = maxZ + depth * 0.5 + 1;
    camera.position.set(0, 0, distance);
    camera.near = 0.1;
    camera.far = distance - minZ + 1;
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
}

function updateCameraFrustum(): void {
    if (!camera || !container.value) return;
    const width = container.value.clientWidth;
    const height = container.value.clientHeight;
    if (width === 0 || height === 0) return;
    const aspect = width / height;
    camera.left = (-frustumSize * aspect) / 2;
    camera.right = (frustumSize * aspect) / 2;
    camera.top = frustumSize / 2;
    camera.bottom = -frustumSize / 2;
    camera.updateProjectionMatrix();
}

function computeFitZoom(): void {
    if (!container.value) return;
    const width = container.value.clientWidth || FIXED_VIEWER_SIZE;
    const height = container.value.clientHeight || FIXED_VIEWER_SIZE;
    const [[minX, minY], [maxX, maxY]] = bounds;
    const spanX = Math.max(maxX - minX, MIN_SPAN);
    const spanY = Math.max(maxY - minY, MIN_SPAN);
    const visibleWidth = frustumSize * (width / height);
    fitZoom = Math.min(frustumSize / (spanY * FIT_MARGIN), visibleWidth / (spanX * FIT_MARGIN));
}

function applyView(): void {
    const cos = Math.cos(view.rotation);
    const sin = Math.sin(view.rotation);
    group.rotation.z = view.rotation;
    group.position.set(
        -(view.targetX * cos - view.targetY * sin),
        -(view.targetX * sin + view.targetY * cos),
        0,
    );
}

function applyZoom(): void {
    if (!camera) return;
    camera.zoom = view.zoom;
    camera.updateProjectionMatrix();
}

// Slider value is the size in px at the fit zoom; points scale with zoom like the plan.
function applyPointSize(): void {
    if (!material || !renderer) return;
    material.size = pointSize.value * renderer.getPixelRatio() * (view.zoom / fitZoom);
}

function setZoom(zoom: number): void {
    view.zoom = THREE.MathUtils.clamp(zoom, fitZoom * ZOOM_OUT_FACTOR, fitZoom * ZOOM_IN_FACTOR);
    applyZoom();
    applyPointSize();
    updateScaleBar();
}

function clampTarget(): void {
    const [[minX, minY], [maxX, maxY]] = bounds;
    const marginX = (maxX - minX) * PAN_MARGIN;
    const marginY = (maxY - minY) * PAN_MARGIN;
    view.targetX = THREE.MathUtils.clamp(view.targetX, minX - marginX, maxX + marginX);
    view.targetY = THREE.MathUtils.clamp(view.targetY, minY - marginY, maxY + marginY);
}

function panBy(dx: number, dy: number): void {
    if (!container.value) return;
    const canvasHeight = container.value.clientHeight || FIXED_VIEWER_SIZE;
    const worldPerPixel = frustumSize / (canvasHeight * view.zoom);
    const cos = Math.cos(view.rotation);
    const sin = Math.sin(view.rotation);
    const worldDx = -dx * worldPerPixel;
    const worldDy = dy * worldPerPixel;
    view.targetX += worldDx * cos + worldDy * sin;
    view.targetY += -worldDx * sin + worldDy * cos;
    clampTarget();
    applyView();
}

function resetView(): void {
    const [[minX, minY], [maxX, maxY]] = bounds;
    computeFitZoom();
    view.targetX = (minX + maxX) / 2;
    view.targetY = (minY + maxY) / 2;
    view.rotation = 0;
    setZoom(fitZoom);
    applyView();
}

function updateScaleBar(): void {
    const cmPerUnit = props.meta?.cm_per_unit;
    if (!renderer || cmPerUnit == null || cmPerUnit <= 0) {
        scaleBarWidthPx.value = 0;
        return;
    }
    const canvasHeightPx = renderer.domElement.clientHeight || FIXED_VIEWER_SIZE;
    const pxPerUnit = (canvasHeightPx * view.zoom) / frustumSize;
    scaleBarWidthPx.value = (100 / cmPerUnit) * pxPerUnit;
}

function updateRendererToElementSize(): void {
    if (!renderer || !container.value) return;
    const width = container.value.clientWidth;
    const height = container.value.clientHeight;
    if (width === 0 || height === 0) return;
    renderer.setSize(width, height);
    updateCameraFrustum();
    computeFitZoom();
    applyPointSize();
    updateScaleBar();
}

function startPinch(): void {
    const [a, b] = [...activePointers.values()];
    if (!a || !b) return;
    pinch = {
        distance: Math.hypot(a.x - b.x, a.y - b.y),
        angle: Math.atan2(b.y - a.y, b.x - a.x),
        zoom: view.zoom,
        rotation: view.rotation,
    };
}

function onPointerDown(event: PointerEvent): void {
    if (!renderer) return;
    event.preventDefault();
    renderer.domElement.setPointerCapture(event.pointerId);
    activePointers.set(event.pointerId, {
        x: event.clientX,
        y: event.clientY,
        button: event.button,
    });
    if (activePointers.size === 2) startPinch();
}

function onPointerMove(event: PointerEvent): void {
    const pointer = activePointers.get(event.pointerId);
    if (!pointer) return;
    const dx = event.clientX - pointer.x;
    const dy = event.clientY - pointer.y;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    if (activePointers.size === 2 && pinch) {
        const [a, b] = [...activePointers.values()];
        if (!a || !b) return;
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        const angle = Math.atan2(b.y - a.y, b.x - a.x);
        if (pinch.distance > 0) setZoom(pinch.zoom * (distance / pinch.distance));
        view.rotation = pinch.rotation - (angle - pinch.angle);
        applyView();
        return;
    }
    if (pointer.button === 2) {
        view.rotation -= dx * ROTATE_SPEED;
        applyView();
        return;
    }
    panBy(dx, dy);
}

function onPointerUp(event: PointerEvent): void {
    activePointers.delete(event.pointerId);
    if (activePointers.size < 2) pinch = null;
}

function onWheel(event: WheelEvent): void {
    event.preventDefault();
    setZoom(view.zoom * Math.exp(-event.deltaY * WHEEL_ZOOM_SPEED));
}

function onContextMenu(event: MouseEvent): void {
    event.preventDefault();
}

function rebuildPoints(): void {
    if (!scene || !renderer) return;
    geometry?.dispose();
    geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(props.buffer), 3));
    if (points) {
        points.geometry = geometry;
        return;
    }
    material = new THREE.PointsMaterial({
        color: 0x000000,
        sizeAttenuation: false,
        transparent: true,
        depthWrite: false,
        opacity: pointOpacity.value,
        clippingPlanes: clipPlanes,
    });
    applyPointSize();
    points = new THREE.Points(geometry, material);
    group.add(points);
}

const collection = useAsyncResultCollection();

onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    resizeObserver = null;
    if (renderer) {
        renderer.setAnimationLoop(null);
        renderer.domElement.remove();
        renderer.dispose();
        renderer = null;
    }
    geometry?.dispose();
    material?.dispose();
    geometry = null;
    material = null;
    points = null;
    scene = null;
    camera = null;
});

onMounted(() => {
    collection.value.add(
        'setup',
        // eslint-disable-next-line require-yield
        AsyncResult.run(function* () {
            if (!container.value) {
                return;
            }

            scene = new THREE.Scene();
            scene.add(group);

            camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);

            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setClearColor(0xffffff, 1);
            renderer.localClippingEnabled = true;
            const initialWidth = props.fill ? container.value.clientWidth : FIXED_VIEWER_SIZE;
            const initialHeight = props.fill ? container.value.clientHeight : FIXED_VIEWER_SIZE;
            renderer.setSize(initialWidth, initialHeight);
            container.value.appendChild(renderer.domElement);

            applyBoundsAndCamera();
            updateCameraFrustum();
            rebuildPoints();

            if (props.fill) {
                updateRendererToElementSize();
                resizeObserver = new ResizeObserver(() => updateRendererToElementSize());
                resizeObserver.observe(container.value);
            }

            const canvas = renderer.domElement;
            canvas.addEventListener('pointerdown', onPointerDown);
            canvas.addEventListener('pointermove', onPointerMove);
            canvas.addEventListener('pointerup', onPointerUp);
            canvas.addEventListener('pointercancel', onPointerUp);
            canvas.addEventListener('wheel', onWheel, { passive: false });
            canvas.addEventListener('contextmenu', onContextMenu);

            resetView();

            renderer.setAnimationLoop(() => {
                if (renderer && scene && camera) {
                    renderer.render(scene, camera);
                }
            });
        }),
    );
});

watch(
    () => props.buffer,
    () => {
        rebuildPoints();
        applyBoundsAndCamera();
        resetView();
    },
);

watch(
    () => props.meta,
    () => {
        applyBoundsAndCamera();
        resetView();
    },
);

watch(pointSize, (value) => {
    window.localStorage.setItem(`plan-point-size:${props.reconstructionId}`, String(value));
    applyPointSize();
});

watch(pointOpacity, (value) => {
    window.localStorage.setItem(`plan-point-opacity:${props.reconstructionId}`, String(value));
    if (material) {
        material.opacity = value;
    }
});

watch(zRange, (value) => {
    minPlane.constant = value === null ? CLIP_OPEN : -value.min;
    maxPlane.constant = value === null ? CLIP_OPEN : value.max;
});
</script>

<template>
    <div class="viewer-root" :class="{ 'viewer-fill': fill }">
        <div class="points-toolbar">
            <span class="text-caption text-grey-7">{{ t('plans.points.pointSize') }}</span>
            <q-slider
                v-model="pointSize"
                :min="POINT_SIZE_MIN"
                :max="POINT_SIZE_MAX"
                :step="POINT_SIZE_STEP"
                :label-value="formatValue(pointSize, POINT_SIZE_STEP)"
                label
                dense
            />
            <span class="text-caption text-grey-7">{{ t('plans.points.pointOpacity') }}</span>
            <q-slider
                v-model="pointOpacity"
                :min="POINT_OPACITY_MIN"
                :max="POINT_OPACITY_MAX"
                :step="POINT_OPACITY_STEP"
                :label-value="formatValue(pointOpacity, POINT_OPACITY_STEP)"
                label
                dense
            />
        </div>
        <div class="viewer-body">
            <div class="canvas-area">
                <div ref="container" class="canvas-container">
                    <div v-if="hasScale" class="scale-overlay" aria-label="Scale: 1 meter">
                        <div class="scale-bar" :style="{ width: `${scaleBarWidthPx}px` }" />
                        <div class="scale-text">1 m</div>
                    </div>
                </div>
            </div>
            <plan-point-density-bar
                v-model="zRange"
                :buffer="buffer"
                :meta="meta"
                :reconstruction-id="reconstructionId"
            />
        </div>
    </div>
</template>

<style scoped>
.viewer-root {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    width: 700px;
    max-width: 95vw;
    height: 700px;
}

.viewer-fill {
    position: absolute;
    inset: 0;
    width: auto;
    max-width: none;
    height: auto;
}

.points-toolbar {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 8px 16px;
    align-items: center;
    /* 16px side padding keeps the drag bubble (~10px past the slider box) inside the drawer. */
    padding: 8px 16px;
    background: #fafafa;
    border-bottom: 1px solid #e5e5ea;
}

/* The drag bubble overflows ~34px above the track; ancestors up to the drawer
   scroll container have no overflow, so it shows over the tools row, unclipped. */

/* The empty marker-labels strip adds 24px of dead space under the track;
   hiding it keeps the rows tight and centers the caption on the track line. */
.points-toolbar :deep(.q-slider__marker-labels-container) {
    display: none;
}

.viewer-body {
    display: flex;
    flex: 1;
    min-height: 0;
}

.canvas-area {
    position: relative;
    flex: 1;
    min-width: 0;
    min-height: 0;
}

.canvas-container {
    position: absolute;
    inset: 0;
    background: #fff;
    border-radius: 8px;
    overflow: hidden;
}

.canvas-container :deep(canvas) {
    display: block;
    touch-action: none;
}

.scale-overlay {
    position: absolute;
    left: 12px;
    bottom: 12px;
    z-index: 30;
    pointer-events: none;
    background: #fff;
    color: #111;
    border: 1px solid #e5e5ea;
    border-radius: 6px;
    padding: 8px 10px;
    display: grid;
    gap: 6px;
}

.scale-bar {
    height: 5px;
    background: #000;
    border-radius: 2px;
}

.scale-text {
    font-size: 12px;
    font-weight: 600;
    line-height: 1;
}
</style>
