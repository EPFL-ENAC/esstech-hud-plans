<template>
    <section class="q-px-md" :aria-label="t('buildings.map.locations')" :aria-busy="isLoading">
        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ data ? t('buildings.map.refreshFailed') : t('buildings.map.loadFailed') }}
            <template #action>
                <q-btn flat :label="t('common.retry')" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <div v-if="state.status === 'pending'" class="q-py-xl text-center" role="status">
            <q-spinner color="primary" size="2em" class="q-mr-sm" />
            {{ t('buildings.map.loading') }}
        </div>
        <p v-else-if="data?.length === 0" class="text-grey-7" role="status">
            {{ t('buildings.map.empty') }}
        </p>
        <div v-else-if="isLoading && data" class="text-grey-7 q-mb-sm" role="status">
            <q-spinner color="primary" class="q-mr-sm" />
            {{ t('buildings.map.refreshing') }}
        </div>

        <q-banner v-if="mapError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ mapError }}
            <template #action>
                <q-btn flat :label="t('buildings.map.retry')" @click="retryMap" />
            </template>
        </q-banner>
        <q-card v-show="data && data.length > 0" flat bordered square class="overflow-hidden">
            <div ref="mapContainer" class="buildings-map" :aria-label="t('buildings.map.label')" />
        </q-card>
    </section>
</template>

<script setup lang="ts">
import {
    computed,
    nextTick,
    onActivated,
    onBeforeUnmount,
    onDeactivated,
    onMounted,
    ref,
    watch,
} from 'vue';
import { useRouter } from 'vue-router';
import {
    LngLatBounds,
    Map as MapLibreMap,
    Marker,
    NavigationControl,
    Popup,
    setWorkerUrl,
} from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { BuildingLocation } from 'src/lib/buildings';
import { createBuildingsMapStyle } from 'src/lib/buildings-map';
import { useBuildingLocationsQuery } from 'src/queries/buildings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

// Let Vite bundle the worker and its imports for both development and production.
setWorkerUrl(mapWorkerUrl);

const router = useRouter();
const { data, state, asyncStatus, refetch } = useBuildingLocationsQuery();
const isLoading = computed(() => asyncStatus.value === 'loading');
const mapContainer = ref<HTMLDivElement | null>(null);
const mapError = ref('');
let map: MapLibreMap | undefined;
let markers: Marker[] = [];
let renderedLocations: BuildingLocation[] | undefined;
let resizeObserver: ResizeObserver | undefined;
let active = true;
let fitted = false;

function buildingName(building: BuildingLocation): string {
    return building.name.trim() || t('buildings.untitled');
}

function popupContent(buildings: BuildingLocation[]): HTMLElement {
    const list = document.createElement('ul');
    list.className = 'building-map-popup';
    for (const building of buildings) {
        const item = document.createElement('li');
        const link = document.createElement('a');
        const path = `/building/${building.id}`;
        link.href = router.resolve(path).href;
        link.textContent = buildingName(building);
        link.onclick = (event) => {
            if (
                event.button !== 0 ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                event.altKey
            )
                return;
            event.preventDefault();
            void router.push(path);
        };
        item.append(link);
        list.append(item);
    }
    return list;
}

function updateMarkers(locations: BuildingLocation[]) {
    if (!map || locations === renderedLocations) return;
    markers.forEach((marker) => marker.remove());
    markers = [];
    const groups = new Map<string, BuildingLocation[]>();
    for (const building of locations) {
        const key = `${building.longitude},${building.latitude}`;
        const group = groups.get(key) ?? [];
        group.push(building);
        groups.set(key, group);
    }
    const bounds = new LngLatBounds();
    for (const buildings of groups.values()) {
        const building = buildings[0]!;
        const position: [number, number] = [building.longitude, building.latitude];
        bounds.extend(position);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'building-map-marker';
        button.textContent = buildings.length > 1 ? String(buildings.length) : '●';
        button.setAttribute(
            'aria-label',
            buildings.length > 1
                ? t('buildings.map.buildingsAtLocation', buildings.length)
                : buildingName(building),
        );
        const marker = new Marker({ element: button })
            .setLngLat(position)
            .setPopup(
                new Popup({ offset: 20, maxWidth: '280px' }).setDOMContent(popupContent(buildings)),
            )
            .addTo(map);
        // Handle native button activation once; MapLibre also listens for keypress.
        button.onkeydown = (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                marker.togglePopup();
            }
        };
        markers.push(marker);
    }
    if (!fitted && !bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 48, maxZoom: 16, duration: 0 });
        fitted = true;
    }
    renderedLocations = locations;
}

function syncMap() {
    if (!active || !mapContainer.value || !data.value) return;
    if (!map && data.value.length > 0 && !mapError.value) {
        try {
            map = new MapLibreMap({
                container: mapContainer.value,
                style: createBuildingsMapStyle(),
                center: [0, 0],
                zoom: 0,
                maxZoom: 19,
                renderWorldCopies: false,
                attributionControl: { compact: false },
            });
            map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
            map.on('error', () => {
                mapError.value = t('buildings.map.tilesFailed');
            });
        } catch {
            mapError.value = t('buildings.map.initializeFailed');
            destroyMap();
            return;
        }
    }
    updateMarkers(data.value);
}

function destroyMap() {
    markers.forEach((marker) => marker.remove());
    markers = [];
    map?.remove();
    map = undefined;
    renderedLocations = undefined;
    // A WebGL initialization failure can leave a partially constructed canvas.
    mapContainer.value?.replaceChildren();
}

function retryMap() {
    const camera = map && { center: map.getCenter(), zoom: map.getZoom() };
    destroyMap();
    mapError.value = '';
    fitted = false;
    syncMap();
    if (camera && map) map.jumpTo(camera);
}

watch(data, syncMap, { flush: 'post' });
onMounted(() => {
    resizeObserver = new ResizeObserver(() => {
        if (active) map?.resize();
    });
    if (mapContainer.value) resizeObserver.observe(mapContainer.value);
    syncMap();
});
onActivated(async () => {
    active = true;
    await nextTick();
    if (active) {
        map?.resize();
        syncMap();
    }
});
onDeactivated(() => {
    active = false;
    map?.stop();
});
onBeforeUnmount(() => {
    active = false;
    resizeObserver?.disconnect();
    destroyMap();
});
</script>

<style scoped>
.buildings-map {
    height: clamp(320px, 65vh, 600px);
}

.buildings-map :deep(.building-map-marker) {
    width: 32px;
    height: 32px;
    border: 2px solid white;
    border-radius: 50%;
    background: var(--q-primary);
    color: white;
    font:
        600 14px Roboto,
        sans-serif;
    box-shadow: 0 1px 5px #0005;
    cursor: pointer;
}

.buildings-map :deep(.building-map-marker:focus-visible) {
    outline: 3px solid var(--q-dark);
    outline-offset: 3px;
}

.buildings-map :deep(.building-map-popup) {
    list-style: none;
    padding: 8px 12px;
    margin: 0;
    max-height: 200px;
    overflow: auto;
}

.buildings-map :deep(.building-map-popup a) {
    display: block;
    padding: 6px 0;
    color: var(--q-primary);
    overflow-wrap: anywhere;
}
</style>
