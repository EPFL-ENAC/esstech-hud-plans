<template>
    <div class="building-location-map rounded-borders overflow-hidden bg-grey-2">
        <div
            v-show="hasCoordinates && !mapError"
            ref="mapContainer"
            class="full-width full-height"
            role="group"
            :aria-label="t('buildings.map.location', { latitude, longitude })"
        />
        <div
            v-if="!hasCoordinates || mapError"
            class="absolute-full column flex-center q-pa-md text-center text-grey-7"
            role="status"
        >
            <span>{{ mapError || t('buildings.map.coordinatesHint') }}</span>
            <q-btn
                v-if="mapError"
                flat
                :label="t('buildings.map.retry')"
                color="primary"
                @click="retryMap"
            />
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { createBuildingsMapStyle } from 'src/lib/buildings-map';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

setWorkerUrl(mapWorkerUrl);

const props = withDefaults(
    defineProps<{
        latitude: number | null;
        longitude: number | null;
        draggable?: boolean;
    }>(),
    { draggable: false },
);
const emit = defineEmits<{ coordsChange: [latitude: number, longitude: number] }>();
const mapContainer = ref<HTMLDivElement | null>(null);
const mapError = ref('');
const hasCoordinates = computed(
    () =>
        props.latitude !== null &&
        Number.isFinite(props.latitude) &&
        props.latitude >= -90 &&
        props.latitude <= 90 &&
        props.longitude !== null &&
        Number.isFinite(props.longitude) &&
        props.longitude >= -180 &&
        props.longitude <= 180,
);

let map: MapLibreMap | undefined;
let marker: Marker | undefined;
let resizeObserver: ResizeObserver | undefined;
let suppressedCenter: [number, number] | null = null;

function destroyMap() {
    marker?.remove();
    marker = undefined;
    map?.remove();
    map = undefined;
    suppressedCenter = null;
    // WebGL initialization may leave a partially constructed canvas behind.
    mapContainer.value?.replaceChildren();
}

function syncMap() {
    if (!hasCoordinates.value) {
        destroyMap();
        mapError.value = '';
        return;
    }
    if (!mapContainer.value || mapError.value) return;
    const center: [number, number] = [props.longitude!, props.latitude!];
    try {
        if (!map) {
            map = new MapLibreMap({
                container: mapContainer.value,
                style: createBuildingsMapStyle(),
                center,
                zoom: 16,
                maxZoom: 19,
                renderWorldCopies: false,
                attributionControl: { compact: false },
            });
            map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
            map.on('error', () => {
                mapError.value = t('buildings.map.previewLoadFailed');
            });
            marker = new Marker({ draggable: props.draggable }).setLngLat(center).addTo(map);
            marker.on('dragend', () => {
                const lngLat = marker?.getLngLat();
                if (!lngLat) return;
                const latitude = Number(lngLat.lat.toFixed(6));
                const longitude = Number(lngLat.lng.toFixed(6));
                if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
                    // The props will take these values next; do not recenter.
                    suppressedCenter = [longitude, latitude];
                    emit('coordsChange', latitude, longitude);
                } else {
                    suppressedCenter = null;
                }
            });
        } else if (
            suppressedCenter !== null &&
            Math.abs(center[0] - suppressedCenter[0]) <= 1e-6 &&
            Math.abs(center[1] - suppressedCenter[1]) <= 1e-6
        ) {
            // The change comes from a drag end: keep the camera where it is.
            suppressedCenter = null;
            marker?.setLngLat(center).setDraggable(props.draggable);
        } else {
            marker?.setLngLat(center).setDraggable(props.draggable);
            map.jumpTo({ center, zoom: 16 });
        }
        map.resize();
    } catch {
        mapError.value = t('buildings.map.previewDisplayFailed');
        destroyMap();
    }
}

async function retryMap() {
    destroyMap();
    mapError.value = '';
    await nextTick();
    syncMap();
}

watch(() => [props.latitude, props.longitude], syncMap, { flush: 'post' });
onMounted(() => {
    resizeObserver = new ResizeObserver(() => map?.resize());
    if (mapContainer.value) resizeObserver.observe(mapContainer.value);
    syncMap();
});
onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    destroyMap();
});
</script>

<style scoped>
.building-location-map {
    position: relative;
    width: 100%;
    height: 200px;
}
</style>
