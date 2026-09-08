import type { StyleSpecification } from 'maplibre-gl';

export function createBuildingsMapStyle(): StyleSpecification {
    return {
        version: 8,
        sources: {
            openstreetmap: {
                type: 'raster',
                tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                tileSize: 256,
                minzoom: 0,
                maxzoom: 19,
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            },
        },
        layers: [{ id: 'openstreetmap', type: 'raster', source: 'openstreetmap' }],
    };
}
