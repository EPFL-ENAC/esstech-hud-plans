export interface ZAxisRange {
    min: number;
    max: number;
}

export interface ZDistribution {
    /** Trimmed Z axis drawn by the bar, bottom first. */
    axis: ZAxisRange;
    /** Points per bin over `axis`, index 0 at the bottom. */
    counts: Uint32Array;
    maxCount: number;
    /** Centre of the first density peak from the bottom, null on an empty cloud. */
    floorZ: number | null;
}

export interface HeightTick {
    /** 0 at the bottom of the axis, 1 at the top. */
    fraction: number;
    label: string;
}

export const Z_BIN_COUNT = 300;
/** Share of the points trimmed at each end of the axis. */
export const AXIS_PERCENTILE = 0.005;
export const DEFAULT_SLAB_METERS = 2;
export const DEFAULT_SLAB_FRACTION = 0.1;
/** The default band starts above the floor, so floor points never clip by accident. */
export const DEFAULT_FLOOR_CLEARANCE_METERS = 0.1;
export const DEFAULT_FLOOR_CLEARANCE_FRACTION = 0.05;

const HEIGHT_TICK_STEPS = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];
const MAX_HEIGHT_TICKS = 5;
const PERCENT_STEPS = [0.05, 0.1, 0.2, 0.25, 0.5, 1];

function scanZRange(positions: Float32Array): ZAxisRange {
    let min = Infinity;
    let max = -Infinity;
    for (let i = 2; i < positions.length; i += 3) {
        const z = positions[i]!;
        if (z < min) min = z;
        if (z > max) max = z;
    }
    return { min, max };
}

function binCounts(positions: Float32Array, axis: ZAxisRange): Uint32Array {
    const counts = new Uint32Array(Z_BIN_COUNT);
    const binWidth = (axis.max - axis.min) / Z_BIN_COUNT;
    if (!(binWidth > 0)) return counts;
    for (let i = 2; i < positions.length; i += 3) {
        const z = positions[i]!;
        if (z < axis.min || z > axis.max) continue;
        const index = Math.min(Math.floor((z - axis.min) / binWidth), Z_BIN_COUNT - 1);
        counts[index] = counts[index]! + 1;
    }
    return counts;
}

function trimAxis(raw: ZAxisRange, counts: Uint32Array): ZAxisRange {
    const binWidth = (raw.max - raw.min) / Z_BIN_COUNT;
    let total = 0;
    for (const count of counts) total += count;
    if (total === 0) return raw;

    const lowTarget = total * AXIS_PERCENTILE;
    let cumulative = 0;
    let lowIndex = 0;
    for (let i = 0; i < Z_BIN_COUNT; i++) {
        cumulative += counts[i]!;
        if (cumulative > lowTarget) {
            lowIndex = i;
            break;
        }
    }

    cumulative = 0;
    let highIndex = Z_BIN_COUNT - 1;
    for (let i = Z_BIN_COUNT - 1; i >= 0; i--) {
        cumulative += counts[i]!;
        if (cumulative > lowTarget) {
            highIndex = i;
            break;
        }
    }

    if (highIndex <= lowIndex) return raw;
    return { min: raw.min + lowIndex * binWidth, max: raw.min + (highIndex + 1) * binWidth };
}

/**
 * Index of the first bin higher than both its neighbours, or -1 when the
 * histogram has no such bin. Missing neighbours count as empty bins.
 */
export function firstLocalMaximumIndex(counts: ArrayLike<number>): number {
    for (let i = 0; i < counts.length; i++) {
        const count = counts[i]!;
        if (count > (counts[i - 1] ?? 0) && count > (counts[i + 1] ?? 0)) return i;
    }
    return -1;
}

function densestBinIndex(counts: ArrayLike<number>): number {
    let best = -1;
    let bestCount = 0;
    for (let i = 0; i < counts.length; i++) {
        if (counts[i]! > bestCount) {
            best = i;
            bestCount = counts[i]!;
        }
    }
    return best;
}

/**
 * Histogram of the Z values and the axis kept for the bar. A single pass when
 * `rawRange` is known, two passes otherwise. No sort, so millions of points stay
 * cheap. Histogram is not reused here: it needs a Float64Array copy of every Z.
 */
export function computeZDistribution(
    positions: Float32Array,
    rawRange?: ZAxisRange | null,
): ZDistribution {
    const raw = rawRange ?? scanZRange(positions);
    // Finite axis even for an empty or flat cloud: keeps the slider's min/max usable.
    const empty: ZDistribution = {
        axis: { min: 0, max: 0 },
        counts: new Uint32Array(Z_BIN_COUNT),
        maxCount: 0,
        floorZ: null,
    };
    if (!Number.isFinite(raw.min) || !Number.isFinite(raw.max) || raw.max <= raw.min) return empty;

    const coarse = binCounts(positions, raw);
    const axis = trimAxis(raw, coarse);
    const counts =
        axis.min === raw.min && axis.max === raw.max ? coarse : binCounts(positions, axis);

    let maxCount = 0;
    for (const count of counts) if (count > maxCount) maxCount = count;
    if (maxCount === 0) return { ...empty, axis };

    const localMaximum = firstLocalMaximumIndex(counts);
    const floorIndex = localMaximum >= 0 ? localMaximum : densestBinIndex(counts);
    const binWidth = (axis.max - axis.min) / Z_BIN_COUNT;
    return { axis, counts, maxCount, floorZ: axis.min + (floorIndex + 0.5) * binWidth };
}

export function barRatio(count: number, maxCount: number, useSquareRoot: boolean): number {
    if (!(maxCount > 0)) return 0;
    const ratio = Math.min(Math.max(count / maxCount, 0), 1);
    return useSquareRoot ? Math.sqrt(ratio) : ratio;
}

/** Keeps `range` inside `axis` and at least one bin tall. */
export function clampZRange(range: ZAxisRange, axis: ZAxisRange): ZAxisRange {
    const span = Math.max(axis.max - axis.min, 0);
    const minSpan = span / Z_BIN_COUNT;
    const min = Math.min(Math.max(range.min, axis.min), axis.max - minSpan);
    const max = Math.min(Math.max(range.max, min + minSpan), axis.max);
    return { min, max };
}

export function defaultZRange(distribution: ZDistribution, cmPerUnit: number | null): ZAxisRange {
    const { axis, floorZ } = distribution;
    const span = axis.max - axis.min;
    const scaled = cmPerUnit != null && cmPerUnit > 0;
    const toWorld = (metres: number) => (metres * 100) / cmPerUnit!;
    const clearance = scaled
        ? toWorld(DEFAULT_FLOOR_CLEARANCE_METERS)
        : span * DEFAULT_FLOOR_CLEARANCE_FRACTION;
    const slab = scaled ? toWorld(DEFAULT_SLAB_METERS) : span * DEFAULT_SLAB_FRACTION;
    const bottom = (floorZ ?? axis.min) + clearance;
    return clampZRange({ min: bottom, max: bottom + slab }, axis);
}

/** 0 at the bottom of the axis, 1 at the top. */
export function heightFraction(z: number, axis: ZAxisRange): number {
    const span = axis.max - axis.min;
    if (!(span > 0)) return 0;
    return Math.min(Math.max((z - axis.min) / span, 0), 1);
}

/**
 * Height labels above the detected floor: the floor always reads "0 m", so a tick
 * exists there and lower ticks go negative. `floorZ` falls back to the axis bottom.
 */
export function buildHeightTicks(
    axis: ZAxisRange,
    floorZ: number | null,
    cmPerUnit: number | null,
): HeightTick[] {
    const span = axis.max - axis.min;
    if (!(span > 0)) return [];
    const datum = floorZ === null ? axis.min : Math.min(Math.max(floorZ, axis.min), axis.max);
    const metresPerUnit = cmPerUnit != null && cmPerUnit > 0 ? cmPerUnit / 100 : null;

    // Steps are metres on a scaled cloud, fractions of the axis height otherwise.
    const units = metresPerUnit === null ? PERCENT_STEPS : HEIGHT_TICK_STEPS;
    const worldSpan = (unit: number) =>
        metresPerUnit === null ? unit * span : unit / metresPerUnit;
    const unitStep =
        units.find((unit) => span / worldSpan(unit) <= MAX_HEIGHT_TICKS - 1) ??
        units[units.length - 1]!;
    const worldStep = worldSpan(unitStep);

    const first = Math.ceil((axis.min - datum) / worldStep - 1e-9);
    const last = Math.floor((axis.max - datum) / worldStep + 1e-9);
    const ticks: HeightTick[] = [];
    for (let index = first; index <= last; index++) {
        ticks.push({
            fraction: (datum + index * worldStep - axis.min) / span,
            label:
                metresPerUnit === null
                    ? `${Math.round(index * unitStep * 100)} %`
                    : `${(index * unitStep).toFixed(stepDecimals(unitStep))} m`,
        });
    }
    return ticks;
}

function stepDecimals(step: number): number {
    return step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
}
