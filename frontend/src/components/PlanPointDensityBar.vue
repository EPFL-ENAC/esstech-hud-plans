<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ReconstructionPointCloudMeta } from 'src/lib/buildings';
import {
    Z_BIN_COUNT,
    barRatio,
    buildHeightTicks,
    clampZRange,
    computeZDistribution,
    defaultZRange,
    heightFraction,
    type ZAxisRange,
    type ZDistribution,
} from 'src/lib/maths/zDistribution';

/** Set to false to draw the density bars linearly instead of on a square root scale. */
const USE_SQUARE_ROOT_SCALE = true;
const BAR_COLOR = '#dcdce2';

const props = defineProps<{
    buffer: ArrayBuffer;
    meta: ReconstructionPointCloudMeta | null;
    reconstructionId: string;
}>();

const range = defineModel<ZAxisRange | null>({ default: null });

const { t } = useI18n();

const distribution = ref<ZDistribution | null>(null);
const canvas = useTemplateRef<HTMLCanvasElement>('canvas');
const bar = useTemplateRef<HTMLDivElement>('bar');
let resizeObserver: ResizeObserver | null = null;

const scale = computed(() => props.meta?.cm_per_unit ?? null);
const axis = computed<ZAxisRange | null>(() => distribution.value?.axis ?? null);
const axisMin = computed(() => axis.value?.min ?? 0);
const axisMax = computed(() => axis.value?.max ?? 0);
const step = computed(() => {
    const span = axisMax.value - axisMin.value;
    return span > 0 ? span / Z_BIN_COUNT : 0;
});
const ticks = computed(() =>
    distribution.value
        ? buildHeightTicks(distribution.value.axis, distribution.value.floorZ, scale.value)
        : [],
);
const floorFraction = computed(() =>
    distribution.value?.floorZ == null
        ? null
        : heightFraction(distribution.value.floorZ, distribution.value.axis),
);
// Kept band: a translucent primary wash between the two heights.
const selectionStyle = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return null;
    return {
        top: `calc(100% - ${axisOffset(heightFraction(current.max, currentAxis))})`,
        bottom: axisOffset(heightFraction(current.min, currentAxis)),
    };
});
// One opaque green line per height, so the band edges read without the handles.
const limitStyles = computed(() => {
    const current = range.value;
    const currentAxis = axis.value;
    if (current === null || currentAxis === null) return [];
    return [current.min, current.max].map((z) => ({
        bottom: axisOffset(heightFraction(z, currentAxis)),
    }));
});

// Clamped on write so the two handles can never collapse the selection to nothing.
const clampedRange = computed<ZAxisRange | null>({
    get: () => range.value,
    set: (value) => {
        range.value = value !== null && axis.value ? clampZRange(value, axis.value) : value;
    },
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

function readStoredRange(storedAxis: ZAxisRange): ZAxisRange | null {
    const raw = readStorage(storageKey());
    if (raw === null) return null;
    try {
        const parsed = JSON.parse(raw) as Partial<ZAxisRange> | null;
        if (parsed === null || !Number.isFinite(parsed.min) || !Number.isFinite(parsed.max)) {
            return null;
        }
        return clampZRange({ min: parsed.min as number, max: parsed.max as number }, storedAxis);
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
    const bounds = props.meta?.bounds;
    const raw = bounds ? { min: bounds[0][2], max: bounds[1][2] } : null;
    const next = computeZDistribution(new Float32Array(props.buffer), raw);
    distribution.value = next;
    // A flat or empty cloud has no axis to select on: no range means "keep every point".
    range.value =
        next.axis.max > next.axis.min
            ? (readStoredRange(next.axis) ?? defaultZRange(next, scale.value))
            : null;
    draw();
}

function onRangeChange(value: ZAxisRange): void {
    if (!axis.value) return;
    writeStorage(storageKey(), JSON.stringify(clampZRange(value, axis.value)));
}

function tickTransform(fraction: number): string {
    if (fraction <= 0) return 'translateY(0)';
    if (fraction >= 1) return 'translateY(100%)';
    return 'translateY(50%)';
}

function axisOffset(fraction: number): string {
    return `calc(var(--density-inset) + (100% - 2 * var(--density-inset)) * ${fraction})`;
}

onMounted(() => {
    rebuild();
    resizeObserver = new ResizeObserver(draw);
    if (bar.value) resizeObserver.observe(bar.value);
});

onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    resizeObserver = null;
});

watch(() => [props.buffer, props.meta, props.reconstructionId], rebuild);
</script>

<template>
    <div ref="bar" class="density-bar" role="group" :aria-label="t('plans.points.density')">
        <canvas ref="canvas" class="density-histogram" aria-hidden="true" />
        <div
            v-if="selectionStyle"
            class="density-selection"
            :style="selectionStyle"
            aria-hidden="true"
        />
        <div
            v-if="floorFraction !== null"
            class="density-floor-line"
            :style="{ bottom: axisOffset(floorFraction) }"
            aria-hidden="true"
        />
        <div
            v-for="(limit, index) in limitStyles"
            :key="index"
            class="density-limit"
            :style="limit"
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
        <!-- `reverse` is required: Quasar puts a vertical slider's minimum at
             the top edge by default, and min must sit on the floor here. -->
        <q-range
            v-if="clampedRange !== null"
            v-model="clampedRange"
            class="density-range"
            vertical
            reverse
            drag-range
            :min="axisMin"
            :max="axisMax"
            :step="step"
            color="dark"
            track-color="transparent"
            inner-track-color="transparent"
            selection-color="transparent"
            track-size="2px"
            thumb-size="14px"
            @change="onRangeChange"
        />
    </div>
</template>

<style scoped>
.density-bar {
    /* Half the thumb size: keeps both handles fully drawn at the floor and the ceiling. */
    --density-inset: 7px;

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
    /* Quasar primary at 12 %: tints the kept band without hiding the bars. */
    background: rgba(25, 118, 210, 0.12);
    pointer-events: none;
}

.density-limit {
    position: absolute;
    right: 0;
    left: 0;
    z-index: 3;
    border-top: 2px solid #2e7d32;
    pointer-events: none;
}

.density-floor-line {
    position: absolute;
    right: 0;
    left: 0;
    z-index: 2;
    border-top: 1px dashed #e11d48;
    pointer-events: none;
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

.density-range {
    position: absolute;
    top: var(--density-inset);
    right: 0;
    bottom: var(--density-inset);
    left: 0;
    z-index: 5;
    height: auto;
}

.density-range :deep(.q-slider__track-container) {
    /* Quasar shrinks this padded container to 26px and left-aligns it in the flex
       root, which would put the handles over the left quarter of the bars. */
    margin: 0 auto;
}

/* White thumb fill keeps the handles readable on top of the bars. */
.density-range :deep(.q-slider__thumb-shape) {
    fill: #fff;
    stroke: #111;
}
</style>
