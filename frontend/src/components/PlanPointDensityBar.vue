<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ReconstructionViewParams } from 'src/lib/buildings';
import {
    Z_BIN_COUNT,
    barRatio,
    buildHeightTicks,
    clampZClip,
    computeZDistribution,
    defaultZClip,
    dragZClip,
    formatHeight,
    heightFraction,
    zBinHeight,
    type ZAxisRange,
    type ZClip,
    type ZClipTarget,
    type ZDistribution,
} from 'src/lib/maths/zDistribution';

/** Set to false to draw the density bars linearly instead of on a square root scale. */
const USE_SQUARE_ROOT_SCALE = true;
const BAR_COLOR = '#dcdce2';
/** Wash on the kept band; the floor and ceiling bands carry a faded share of it. */
const WASH_RGB = '25, 118, 210';
const WASH_ALPHA = 0.12;
const WASH_FADE = 0.5;
/** Band height below which the FLOOR and CEILING labels would not fit. */
const LABEL_MIN_HEIGHT = 18;
/** Distance kept between a band label and a height label, in pixels. */
const LABEL_CLEARANCE = 12;
const KEY_STEP_BINS = 1;
const KEY_STEP_BINS_LARGE = 10;

const props = defineProps<{
    buffer: ArrayBuffer;
    viewParams: ReconstructionViewParams;
    reconstructionId: string;
}>();

const range = defineModel<ZClip | null>({ default: null });

const { t } = useI18n();

const distribution = ref<ZDistribution | null>(null);
const axisHeight = ref(0);
const canvas = useTemplateRef<HTMLCanvasElement>('canvas');
const bar = useTemplateRef<HTMLDivElement>('bar');
const handleLayer = useTemplateRef<HTMLDivElement>('handleLayer');
let resizeObserver: ResizeObserver | null = null;

interface DragState {
    target: ZClipTarget;
    startFraction: number;
    snapshot: ZClip;
}

let drag: DragState | null = null;

const scale = computed(() => props.viewParams.scale);
const axis = computed<ZAxisRange | null>(() => distribution.value?.axis ?? null);
const axisMin = computed(() => axis.value?.min ?? 0);
const axisMax = computed(() => axis.value?.max ?? 0);
const labelCentres = computed(() =>
    spans.value.filter((span) => span.label !== '').map((span) => span.centre),
);
const ticks = computed(() => {
    if (distribution.value === null) return [];
    const centres = labelCentres.value;
    const height = axisHeight.value;
    const ticks = buildHeightTicks(distribution.value.axis, distribution.value.floorZ, scale.value);
    if (!(height > 0)) return ticks;
    return ticks.filter((tick) =>
        centres.every((centre) => Math.abs(tick.fraction - centre) * height >= LABEL_CLEARANCE),
    );
});
const spans = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return [];
    return [
        {
            key: 'floor',
            min: current.clip.min,
            max: current.opaque.min,
            faded: true,
            label: 'plans.points.floorBand',
        },
        {
            key: 'kept',
            min: current.opaque.min,
            max: current.opaque.max,
            faded: false,
            label: null,
        },
        {
            key: 'ceiling',
            min: current.opaque.max,
            max: current.clip.max,
            faded: true,
            label: 'plans.points.ceilingBand',
        },
    ].map((span) => {
        const from = heightFraction(span.min, currentAxis);
        const to = heightFraction(span.max, currentAxis);
        return {
            key: span.key,
            centre: (from + to) / 2,
            label:
                span.label !== null && (to - from) * axisHeight.value >= LABEL_MIN_HEIGHT
                    ? t(span.label)
                    : '',
            style: {
                top: `calc(100% - ${axisOffset(to)})`,
                bottom: axisOffset(from),
                background: `rgba(${WASH_RGB}, ${WASH_ALPHA * (span.faded ? WASH_FADE : 1)})`,
            },
        };
    });
});
// One line per height: solid green on the opacity limits, dashed grey on the clip limits.
const limitStyles = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return [];
    return [
        { z: current.clip.min, dashed: true },
        { z: current.opaque.min, dashed: false },
        { z: current.opaque.max, dashed: false },
        { z: current.clip.max, dashed: true },
    ].map((limit) => ({
        dashed: limit.dashed,
        style: { bottom: axisOffset(heightFraction(limit.z, currentAxis)) },
    }));
});
const bands = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return [];
    return [
        { target: 'ab' as const, min: current.clip.min, max: current.opaque.min },
        { target: 'bc' as const, min: current.opaque.min, max: current.opaque.max },
        { target: 'cd' as const, min: current.opaque.max, max: current.clip.max },
    ].map((band) => ({
        target: band.target,
        style: {
            top: `calc(100% - ${fractionOffset(heightFraction(band.max, currentAxis))})`,
            bottom: fractionOffset(heightFraction(band.min, currentAxis)),
        },
    }));
});
const handles = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return [];
    const handles = [
        {
            key: 'a',
            target: 'a' as const,
            z: current.clip.min,
            label: 'plans.points.clipFloor',
            depth: 2,
        },
        {
            key: 'b',
            target: 'ab' as const,
            z: current.opaque.min,
            label: 'plans.points.opaqueBottom',
            depth: 1,
        },
        {
            key: 'c',
            target: 'cd' as const,
            z: current.opaque.max,
            label: 'plans.points.opaqueTop',
            depth: 1,
        },
        {
            key: 'd',
            target: 'd' as const,
            z: current.clip.max,
            label: 'plans.points.clipCeiling',
            depth: 2,
        },
    ];
    return handles.map((handle) => ({
        key: handle.key,
        target: handle.target,
        depth: handle.depth,
        label: t(handle.label),
        // A and D grab anywhere across the bar, so they win over the bands and over B and C.
        edge: handle.key === 'a' || handle.key === 'd',
        now: handle.z,
        text: distribution.value ? formatHeight(handle.z, distribution.value, scale.value) : '',
        style: { bottom: fractionOffset(heightFraction(handle.z, currentAxis)) },
    }));
});

function storageKey(): string {
    return `plan-z-clip:${props.reconstructionId}`;
}

function readStorage(key: string): string | null {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null; // Storage disabled by the browser.
    }
}

function writeStorage(key: string, value: string | null): void {
    try {
        if (value === null) window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, value);
    } catch {
        // Storage disabled or full: the range still applies for this session.
    }
}

function readStoredClip(storedAxis: ZAxisRange): ZClip | null {
    const raw = readStorage(storageKey());
    if (raw === null) return null;
    try {
        const parsed = JSON.parse(raw) as Partial<ZClip> | null;
        const { clip, opaque } = parsed ?? {};
        if (clip === undefined || opaque === undefined) return null;
        const heights = [clip.min, clip.max, opaque.min, opaque.max];
        if (!heights.every((height) => Number.isFinite(height))) return null;
        return clampZClip({ clip, opaque }, storedAxis);
    } catch {
        return null; // Corrupted value: fall back to the default range.
    }
}

function draw(): void {
    const element = canvas.value;
    const current = distribution.value;
    if (!element || !current) return;
    const width = element.clientWidth;
    const height = element.clientHeight;
    axisHeight.value = height;
    if (width === 0 || height === 0) return;

    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    element.width = Math.round(width * pixelRatio);
    element.height = Math.round(height * pixelRatio);
    const context = element.getContext('2d');
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const binHeight = height / Z_BIN_COUNT;
    context.fillStyle = BAR_COLOR;
    for (let index = 0; index < current.counts.length; index++) {
        const count = current.counts[index]!;
        if (count === 0) continue;
        context.fillRect(
            0,
            height - (index + 1) * binHeight,
            barRatio(count, current.maxCount, USE_SQUARE_ROOT_SCALE) * width,
            // Slight overlap so sub-pixel bin heights do not leave gaps.
            binHeight + 0.6,
        );
    }
}

function rebuild(): void {
    const next = computeZDistribution(new Float32Array(props.buffer));
    distribution.value = next;
    // A flat or empty cloud has no axis to select on: no range means "keep every point".
    range.value =
        next.axis.max > next.axis.min
            ? (readStoredClip(next.axis) ?? defaultZClip(next, scale.value))
            : null;
    draw();
}

function tickTransform(fraction: number): string {
    if (fraction <= 0) return 'translateY(0)';
    if (fraction >= 1) return 'translateY(100%)';
    return 'translateY(50%)';
}

function axisOffset(fraction: number): string {
    return `calc(var(--density-inset) + (100% - 2 * var(--density-inset)) * ${fraction})`;
}

/** Same scale as `axisOffset`, for the children of the already inset handle layer. */
function fractionOffset(fraction: number): string {
    return `${fraction * 100}%`;
}

function fractionAt(event: PointerEvent, element: HTMLElement): number {
    const rect = element.getBoundingClientRect();
    if (!(rect.height > 0)) return 0;
    return Math.min(Math.max(1 - (event.clientY - rect.top) / rect.height, 0), 1);
}

function persist(): void {
    if (range.value !== null) writeStorage(storageKey(), JSON.stringify(range.value));
}

function onPointerDown(event: PointerEvent, target: ZClipTarget): void {
    const current = range.value;
    const element = handleLayer.value;
    if (current === null || element === null || event.button !== 0) return;
    event.preventDefault();
    // preventDefault keeps the click from focusing the handle, which the arrow keys need.
    if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
    drag = { target, startFraction: fractionAt(event, element), snapshot: current };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
}

// Every move is measured from the drag start, so a hit bound does not offset the drag.
function onPointerMove(event: PointerEvent): void {
    const currentAxis = axis.value;
    const element = handleLayer.value;
    if (drag === null || currentAxis === null || element === null) return;
    const delta =
        (fractionAt(event, element) - drag.startFraction) * (currentAxis.max - currentAxis.min);
    range.value = dragZClip(drag.snapshot, drag.target, delta, currentAxis);
}

function onPointerUp(): void {
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onPointerUp);
    if (drag !== null) persist();
    drag = null;
}

function onHandleKey(event: KeyboardEvent, target: ZClipTarget): void {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return;
    const direction = event.key === 'ArrowUp' ? 1 : event.key === 'ArrowDown' ? -1 : 0;
    if (direction === 0) return;
    event.preventDefault();
    const bins = event.shiftKey ? KEY_STEP_BINS_LARGE : KEY_STEP_BINS;
    range.value = dragZClip(
        current,
        target,
        direction * bins * zBinHeight(currentAxis),
        currentAxis,
    );
    persist();
}

onMounted(() => {
    rebuild();
    resizeObserver = new ResizeObserver(draw);
    if (bar.value) resizeObserver.observe(bar.value);
});

onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    resizeObserver = null;
    onPointerUp();
});

watch(() => [props.buffer, props.viewParams, props.reconstructionId], rebuild);
</script>

<template>
    <div ref="bar" class="density-bar" role="group" :aria-label="t('plans.points.density')">
        <canvas ref="canvas" class="density-histogram" aria-hidden="true" />
        <div
            v-for="span in spans"
            :key="span.key"
            class="density-selection"
            :style="span.style"
            aria-hidden="true"
        >
            <span v-if="span.label" class="density-band-label">{{ span.label }}</span>
        </div>
        <div
            v-for="(limit, index) in limitStyles"
            :key="index"
            class="density-limit"
            :class="{ 'density-limit--dashed': limit.dashed }"
            :style="limit.style"
            aria-hidden="true"
        />
        <span
            v-for="tick in ticks"
            :key="tick.label"
            class="density-tick"
            :style="{
                bottom: axisOffset(tick.fraction),
                transform: tickTransform(tick.fraction),
            }"
            aria-hidden="true"
        >
            {{ tick.label }}
        </span>
        <div ref="handleLayer" class="density-handles">
            <div
                v-for="band in bands"
                :key="band.target"
                class="density-band"
                :style="band.style"
                @pointerdown="onPointerDown($event, band.target)"
            />
            <div
                v-for="handle in handles"
                :key="handle.key"
                class="density-handle"
                :class="{ 'density-handle--edge': handle.edge }"
                :style="[handle.style, { zIndex: handle.depth }]"
                role="slider"
                aria-orientation="vertical"
                tabindex="0"
                :aria-label="handle.label"
                :aria-valuemin="axisMin"
                :aria-valuemax="axisMax"
                :aria-valuenow="handle.now"
                :aria-valuetext="handle.text"
                @pointerdown="onPointerDown($event, handle.target)"
                @keydown="onHandleKey($event, handle.target)"
            />
        </div>
    </div>
</template>

<style scoped>
.density-bar {
    /* Half the handle size: keeps every handle fully drawn at the axis ends. */
    --density-inset: 8px;

    position: relative;
    flex: none;
    width: 60px;
    min-height: 0;
    border-left: 1px solid #e5e5ea;
    background: #fff;
}

.density-histogram {
    position: absolute;
    top: var(--density-inset);
    left: 0;
    width: 100%;
    height: calc(100% - 2 * var(--density-inset));
}

.density-selection {
    position: absolute;
    right: 0;
    left: 0;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    pointer-events: none;
}

.density-band-label {
    font-size: 9px;
    font-weight: 600;
    line-height: 1;
    letter-spacing: 0.4px;
    color: #455a64;
    text-shadow: 0 0 3px #fff;
    white-space: nowrap;
}

.density-limit {
    position: absolute;
    right: 0;
    left: 0;
    z-index: 3;
    border-top: 2px solid #2e7d32;
    pointer-events: none;
}

.density-limit--dashed {
    border-top: 2px dashed #9e9e9e;
}

.density-tick {
    position: absolute;
    left: 4px;
    z-index: 4;
    font-size: 10px;
    line-height: 1;
    color: #424242;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    pointer-events: none;
}

.density-handles {
    position: absolute;
    top: var(--density-inset);
    right: 0;
    bottom: var(--density-inset);
    left: 0;
    z-index: 5;
    touch-action: none;
}

.density-band {
    position: absolute;
    right: 0;
    left: 0;
    cursor: grab;
}

.density-handle {
    position: absolute;
    left: 50%;
    width: 16px;
    height: 16px;
    box-sizing: border-box;
    border: 2px solid #111;
    border-radius: 50%;
    background: #fff;
    cursor: grab;
    transform: translate(-50%, 50%);
}

/* A and D grab across the whole bar, so they bite over the bands and over B and C. */
.density-handle--edge {
    right: 0;
    left: 0;
    width: auto;
    height: 16px;
    border: none;
    border-radius: 0;
    background: transparent;
    transform: translateY(50%);
}

.density-handle--edge::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 16px;
    height: 16px;
    box-sizing: border-box;
    border: 2px solid #111;
    border-radius: 50%;
    /* Opaque, so the dashed clip line stops at the handle. */
    background: #fff;
    transform: translate(-50%, -50%);
}

.density-handle:focus-visible {
    outline: 2px solid #1976d2;
    outline-offset: 1px;
}
</style>
