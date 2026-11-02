import assert from 'node:assert/strict';
import { test } from 'node:test';
import { importTypeScript } from './helpers/typescript.mjs';

async function allBuildingsQuery(t, listBuildings) {
    const buildings = await importTypeScript(t, 'src/lib/buildings.ts', {
        'src/i18n/instance': { i18n: {} },
        'boot/api': { baseUrl: 'https://hud.test/api' },
        'src/lib/api': { ApiError: class extends Error {}, requestJson() {} },
        'src/lib/utils/resumableDownload': { downloadResumable() {} },
    });
    const queries = await importTypeScript(t, 'src/queries/buildings.ts', {
        vue: import.meta.resolve('vue'),
        '@pinia/colada': { useQuery: (options) => options },
        'src/composables/useDocumentVisibility': { useDocumentVisibility() {} },
        'src/lib/auth': { getAuthSubject: () => 'owner' },
        'src/lib/buildings': {
            ...buildings,
            listBuildings,
        },
    });
    return queries.useAllBuildingsQuery().query;
}

for (const count of [0, 1, 100, 101, 200]) {
    test(`the all-buildings query loads ${count} items without a trailing request`, async (t) => {
        const buildings = Array.from({ length: count }, (_, id) => ({ id: String(id) }));
        const offsets = [];
        const query = await allBuildingsQuery(t, async ({ offset, limit }) => {
            offsets.push(offset);
            assert.equal(limit, 100);
            return { items: buildings.slice(offset, offset + limit), total: count };
        });

        assert.deepEqual(await query(), buildings);
        assert.deepEqual(
            offsets,
            Array.from({ length: Math.max(1, Math.ceil(count / 100)) }, (_, i) => i * 100),
        );
    });
}

test('the all-buildings query stops on an empty page if records disappear during loading', async (t) => {
    const buildings = Array.from({ length: 100 }, (_, id) => ({ id: String(id) }));
    const offsets = [];
    const query = await allBuildingsQuery(t, async ({ offset }) => {
        offsets.push(offset);
        return { items: offset === 0 ? buildings : [], total: 200 };
    });

    assert.deepEqual(await query(), buildings);
    assert.deepEqual(offsets, [0, 100]);
});
