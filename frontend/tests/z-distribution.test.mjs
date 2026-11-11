import assert from 'node:assert/strict';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

const Z_BIN_COUNT = 300;

function cloud(layers) {
    const positions = [];
    for (const [z, count] of layers) {
        for (let i = 0; i < count; i++) positions.push(0, 0, z);
    }
    return new Float32Array(positions);
}

async function load(t) {
    return importTypeScript(t, 'src/lib/maths/zDistribution.ts', {});
}

test('trims the axis to the 0.5 and 99.5 percentiles', async (t) => {
    const z = await load(t);
    // One outlier at 50 m is 1/420 of the cloud, below the 0.5 % trim.
    const distribution = z.computeZDistribution(
        cloud([
            [0, 300],
            [1, 100],
            [2.5, 19],
            [50, 1],
        ]),
    );
    assert.ok(distribution.axis.min >= 0 && distribution.axis.min <= 0.2);
    assert.ok(distribution.axis.max > 2.5 && distribution.axis.max < 3);
    assert.equal(distribution.counts.length, Z_BIN_COUNT);
    assert.ok(distribution.maxCount > 0);
    assert.ok(distribution.floorZ !== null && Math.abs(distribution.floorZ) < 0.1);
});

test('computes the same distribution with and without a known raw range', async (t) => {
    const z = await load(t);
    const positions = cloud([
        [0, 60],
        [1, 30],
        [-3, 10],
    ]);
    const scanned = z.computeZDistribution(positions);
    const given = z.computeZDistribution(positions, { min: -3, max: 1 });
    assert.deepEqual(given.axis, scanned.axis);
    assert.deepEqual([...given.counts], [...scanned.counts]);
});

test('scans the Z extent, and reports a zero range when empty', async (t) => {
    const z = await load(t);
    assert.deepEqual(
        z.scanZRange(
            cloud([
                [0, 3],
                [2.5, 9],
                [-1, 4],
            ]),
        ),
        { min: -1, max: 2.5 },
    );
    assert.deepEqual(z.scanZRange(new Float32Array()), { min: 0, max: 0 });
});

test('reports no floor on an empty or flat cloud', async (t) => {
    const z = await load(t);
    assert.equal(z.computeZDistribution(new Float32Array()).floorZ, null);
    assert.equal(z.computeZDistribution(cloud([[1.5, 40]])).floorZ, null);
});

test('takes the first local maximum from the bottom', async (t) => {
    const z = await load(t);
    assert.equal(z.firstLocalMaximumIndex([0, 0, 7, 3, 9, 0]), 2);
    assert.equal(z.firstLocalMaximumIndex([7, 0, 0, 0]), 0);
    assert.equal(z.firstLocalMaximumIndex([1, 2, 3]), 2);
    assert.equal(z.firstLocalMaximumIndex([0, 0, 0]), -1);
    assert.equal(z.firstLocalMaximumIndex([4, 4, 4]), -1);
});

test('ignores peaks below the minimum count', async (t) => {
    const z = await load(t);
    assert.equal(z.firstLocalMaximumIndex([3, 1, 9, 1, 2], 5), 2);
    assert.equal(z.firstLocalMaximumIndex([5, 1, 9, 1, 2], 5), 0);
    assert.equal(z.firstLocalMaximumIndex([4, 1, 2], 5), -1);
});

test('skips a floor peak under half of the tallest bin', async (t) => {
    const z = await load(t);
    assert.equal(z.FLOOR_PEAK_MIN_FRACTION, 0.5);

    const distribution = z.computeZDistribution(
        cloud([
            [0, 5],
            [1, 200],
        ]),
    );

    assert.ok(Math.abs(distribution.floorZ - 1) < 0.02);
});

test('scales bars with a square root or linearly', async (t) => {
    const z = await load(t);
    assert.equal(z.barRatio(0, 100, true), 0);
    assert.equal(z.barRatio(100, 100, true), 1);
    assert.equal(z.barRatio(25, 100, true), 0.5);
    assert.equal(z.barRatio(25, 100, false), 0.25);
    assert.equal(z.barRatio(5, 0, false), 0);
});

test('clamps a range into the axis and keeps it one bin tall', async (t) => {
    const z = await load(t);
    const axis = { min: 0, max: 3 };
    assert.deepEqual(z.clampZRange({ min: -5, max: 10 }, axis), { min: 0, max: 3 });
    const collapsed = z.clampZRange({ min: 1, max: 1 }, axis);
    assert.ok(Math.abs(collapsed.max - collapsed.min - 3 / Z_BIN_COUNT) < 1e-12);
});

test('defaults to a two metre slab just above the detected floor', async (t) => {
    const z = await load(t);
    const distribution = z.computeZDistribution(
        cloud([
            [0.5, 200],
            [1.5, 100],
            [5, 50],
        ]),
    );
    const withScale = z.defaultZRange({ ...distribution, floorZ: 1 }, 100);
    assert.ok(Math.abs(withScale.min - 1.1) < 1e-6);
    assert.ok(Math.abs(withScale.max - withScale.min - 2) < 0.05);
    const withoutScale = z.defaultZRange(distribution, null);
    const span = distribution.axis.max - distribution.axis.min;
    assert.ok(Math.abs(withoutScale.max - withoutScale.min - span * 0.1) < 1e-6);
});

test('labels heights above the floor, or in percent without a scale', async (t) => {
    const z = await load(t);
    const axis = { min: 0, max: 3 };
    assert.deepEqual(
        z.buildHeightTicks(axis, 0, 100).map((tick) => tick.label),
        ['0 m', '1 m', '2 m', '3 m'],
    );
    assert.deepEqual(
        z.buildHeightTicks(axis, null, null).map((tick) => tick.label),
        ['0 %', '25 %', '50 %', '75 %', '100 %'],
    );

    // The floor owns the "0 m" label, so a floor above the axis bottom shifts the ticks.
    const raised = z.buildHeightTicks(axis, 0.5, 100);
    assert.deepEqual(
        raised.map((tick) => tick.label),
        ['0 m', '1 m', '2 m'],
    );
    assert.ok(Math.abs(raised[0].fraction - 0.5 / 3) < 1e-9);

    // Below the floor, labels go negative.
    const below = z.buildHeightTicks({ min: 0, max: 3 }, 2, 100);
    assert.deepEqual(
        below.map((tick) => tick.label),
        ['-2 m', '-1 m', '0 m', '1 m'],
    );
});

test('frames the kept band with bands twice the floor clearance thick', async (t) => {
    const z = await load(t);
    const distribution = {
        axis: { min: 0, max: 10 },
        counts: new Uint32Array(Z_BIN_COUNT),
        maxCount: 1,
        floorZ: 0,
    };

    // 100 cm per unit: the clearance is 0.1 m, so each band is 0.2 m thick.
    const scaled = z.defaultZClip(distribution, 100);
    assert.ok(Math.abs(scaled.opaque.min - 0.1) < 1e-9);
    assert.equal(scaled.clip.min, 0);
    assert.ok(Math.abs(scaled.clip.max - (scaled.opaque.max + 0.2)) < 1e-9);

    // No scale: 5 % clearance, 10 % bands.
    const plain = z.defaultZClip(distribution, null);
    assert.ok(Math.abs(plain.opaque.min - 0.5) < 1e-9);
    assert.ok(Math.abs(plain.clip.max - (plain.opaque.max + 1)) < 1e-9);
});

test('orders the four heights and keeps them one bin apart', async (t) => {
    const z = await load(t);
    const gap = 10 / Z_BIN_COUNT;
    const clamped = z.clampZClip(
        { clip: { min: -5, max: 50 }, opaque: { min: 4, max: 2 } },
        { min: 0, max: 10 },
    );
    assert.equal(clamped.clip.min, 0);
    assert.equal(clamped.opaque.min, 4);
    assert.ok(Math.abs(clamped.opaque.max - (4 + gap)) < 1e-12);
    assert.equal(clamped.clip.max, 10);
});

test('moves the grabbed handle or band and compresses at the axis ends', async (t) => {
    const z = await load(t);
    const axis = { min: 0, max: 10 };
    const gap = 10 / Z_BIN_COUNT;
    const start = { clip: { min: 2, max: 6 }, opaque: { min: 3, max: 5 } };
    const move = (target, delta) => z.dragZClip(start, target, delta, axis);

    // A and D resize the floor and ceiling bands only.
    assert.deepEqual(move('a', -0.5), { clip: { min: 1.5, max: 6 }, opaque: { min: 3, max: 5 } });
    assert.deepEqual(move('d', 0.5), { clip: { min: 2, max: 6.5 }, opaque: { min: 3, max: 5 } });
    // A may sit exactly on B: the clip band collapses onto the opacity limit.
    assert.equal(move('a', 5).clip.min, 3);
    assert.equal(move('d', -5).clip.max, 5);

    // The B and C band bodies translate their band.
    assert.deepEqual(move('ab', 0.5), { clip: { min: 2.5, max: 6 }, opaque: { min: 3.5, max: 5 } });
    assert.deepEqual(move('cd', 0.5), { clip: { min: 2, max: 6.5 }, opaque: { min: 3, max: 5.5 } });

    // The kept band moves everything, then the bands pile up one bin apart at the end.
    const up = move('bc', 20);
    assert.equal(up.clip.max, 10);
    assert.equal(up.opaque.max, 10);
    assert.ok(Math.abs(up.opaque.min - (10 - gap)) < 1e-9);
    assert.ok(Math.abs(up.clip.min - (10 - gap)) < 1e-9);

    const down = move('bc', -20);
    assert.equal(down.clip.min, 0);
    assert.equal(down.opaque.min, 0);
    assert.ok(Math.abs(down.opaque.max - gap) < 1e-9);
    assert.ok(Math.abs(down.clip.max - gap) < 1e-9);
});

test('labels a handle height above the floor', async (t) => {
    const z = await load(t);
    const distribution = {
        axis: { min: 0, max: 3 },
        counts: new Uint32Array(Z_BIN_COUNT),
        maxCount: 1,
        floorZ: 1,
    };
    assert.equal(z.formatHeight(2.5, distribution, 100), '1.50 m');
    assert.equal(z.formatHeight(2.5, distribution, null), '50 %');
});
