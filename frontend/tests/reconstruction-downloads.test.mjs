import assert from 'node:assert/strict';
import { test } from 'node:test';
import { downloadFixture } from './helpers/resumable-download.mjs';
import { importTypeScript } from './helpers/typescript.mjs';

const buildingId = 'building / a';
const reconstructionId = 'reconstruction / a';
const payload = new Uint8Array([1, 2, 3, 4, 5, 6]);

async function fixture(t) {
    const download = await downloadFixture(t, { persistent: true });
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test/api' },
        'src/lib/api': { ApiError: class extends Error {}, requestJson() {} },
        'src/lib/resumableDownload': { ResumableDownload: download.ResumableDownload },
    });
    return { ...download, buildings };
}

for (const [helper, resource] of [
    ['getReconstructionVideo', 'video'],
    ['getReconstructionSplat', 'splat'],
    ['getReconstructionPointCloud', 'point-cloud'],
]) {
    const url = `https://hud.test/api/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/${resource}`;

    test(`${resource}: returns the expected data and reuses the completed download`, async (t) => {
        const f = await fixture(t);
        const progress = [];
        const controller = new AbortController();
        f.setFetch(
            () => new Response(payload, { headers: { etag: '"v1"', 'content-length': '6' } }),
        );

        const result = await f.buildings[helper](
            buildingId,
            reconstructionId,
            controller.signal,
            (value) => progress.push(value),
        );
        assert.equal(f.requests[0].url, url);
        assert.deepEqual(progress.at(-1), { loaded: 6, total: 6 });
        assert.equal(f.records.get(url).complete, true);
        if (resource === 'video') {
            assert.ok(result instanceof Blob);
            assert.equal(f.events.filter(([type]) => type === 'materialize').length, 0);
        } else {
            assert.ok(result instanceof ArrayBuffer);
        }
        const bytes = result instanceof Blob ? await result.arrayBuffer() : result;
        assert.deepEqual(new Uint8Array(bytes), payload);

        const cached = await f.buildings[helper](buildingId, reconstructionId, controller.signal);
        const cachedBytes = cached instanceof Blob ? await cached.arrayBuffer() : cached;
        assert.deepEqual(new Uint8Array(cachedBytes), payload);
        assert.equal(f.requests.length, 1);
        assert.equal(f.files.size, 1);
    });

    test(`${resource}: cancellation preserves bytes for a later helper call to resume`, async (t) => {
        const f = await fixture(t);
        const controller = new AbortController();
        const reason = new Error('Paused by the caller');
        f.setFetch(
            () =>
                new Response(
                    new ReadableStream({
                        start(stream) {
                            stream.enqueue(payload.subarray(0, 3));
                        },
                    }),
                    { headers: { etag: '"v1"', 'content-length': '6' } },
                ),
        );

        await assert.rejects(
            f.buildings[helper](buildingId, reconstructionId, controller.signal, ({ loaded }) => {
                if (loaded === 3) controller.abort(reason);
            }),
            (error) => error === reason,
        );
        assert.equal(f.records.get(url).committedBytes, 3);
        assert.equal(f.records.get(url).complete, false);

        f.setFetch(
            () =>
                new Response(payload.subarray(3), {
                    status: 206,
                    headers: { etag: '"v1"', 'content-range': 'bytes 3-5/6' },
                }),
        );
        const resumed = await f.buildings[helper](
            buildingId,
            reconstructionId,
            new AbortController().signal,
        );
        const bytes = resumed instanceof Blob ? await resumed.arrayBuffer() : resumed;
        assert.deepEqual(new Uint8Array(bytes), payload);
        assert.equal(f.requests[1].headers.get('range'), 'bytes=3-');
        assert.equal(f.requests[1].headers.get('if-range'), '"v1"');
    });

    test(`${resource}: propagates network and HTTP failures`, async (t) => {
        const f = await fixture(t);
        const reason = new TypeError('Connection lost');
        f.setFetch(() => {
            throw reason;
        });
        await assert.rejects(
            f.buildings[helper](buildingId, reconstructionId, new AbortController().signal),
            (error) => error === reason,
        );

        f.setFetch(() => new Response(null, { status: 403 }));
        await assert.rejects(
            f.buildings[helper](buildingId, reconstructionId, new AbortController().signal),
            { status: 403 },
        );
    });
}
