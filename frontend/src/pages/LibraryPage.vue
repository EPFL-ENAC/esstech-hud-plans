<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <div class="od-topbar">
            <div class="od-topbar__title">Library</div>
            <q-btn
                flat
                no-caps
                color="primary"
                label="New Capture"
                class="od-topbar__action"
                @click="$router.push('/capture')"
            />
        </div>

        <q-tabs
            v-model="tab"
            no-caps
            indicator-color="primary"
            align="left"
            class="od-library-tabs"
        >
            <q-tab name="list" label="List" />
            <q-tab name="map" label="Map" />
        </q-tabs>

        <q-input v-model="search" outlined placeholder="Search" class="od-search q-my-md">
            <template #prepend>
                <q-icon name="search" />
            </template>
        </q-input>

        <q-list v-if="tab === 'list'" class="od-list-flush">
            <building-list-item
                v-for="building in filteredBuildings"
                :key="building.id"
                :building="building"
                :show-chevron="building.status === 'ready'"
                @click="openBuilding(building.id)"
            />
        </q-list>

        <div v-else class="od-map" style="aspect-ratio: 3/4">
            <svg viewBox="0 0 320 420" class="fit" preserveAspectRatio="xMidYMid slice">
                <rect width="320" height="420" fill="#f2f2f7" />
                <g stroke="#c7c7cc" stroke-width="6" fill="none" stroke-linecap="round">
                    <path d="M-10 80 Q80 60 120 120 T240 100 T340 160" />
                    <path d="M60 -10 Q70 80 40 160 T80 300 T20 430" />
                    <path d="M180 -10 Q190 100 160 200 T200 340 T150 430" />
                    <path d="M280 -10 Q300 90 270 180 T310 320 T260 430" />
                </g>
                <g fill="#e5e5ea">
                    <rect x="90" y="40" width="40" height="30" transform="rotate(12 110 55)" />
                    <rect x="200" y="70" width="50" height="35" transform="rotate(-8 225 87)" />
                    <rect x="50" y="180" width="45" height="30" transform="rotate(6 72 195)" />
                    <rect x="230" y="220" width="35" height="50" transform="rotate(-5 247 245)" />
                    <rect x="120" y="300" width="55" height="35" transform="rotate(10 147 317)" />
                    <rect x="30" y="340" width="40" height="25" transform="rotate(-12 50 352)" />
                    <rect x="260" y="360" width="45" height="30" transform="rotate(8 282 375)" />
                </g>
            </svg>

            <div
                v-for="building in buildingsStore.buildings"
                :key="building.id"
                class="od-map__marker"
                :style="{
                    left: `${(building.x / 320) * 100}%`,
                    top: `${(building.y / 420) * 100}%`,
                }"
                @click="openBuilding(building.id)"
            >
                <div class="od-map__label">{{ building.name }}</div>
                <div class="od-map__pin" />
                <div v-if="building.status === 'processing'" class="od-map__callout">
                    <div class="od-map__callout-title">{{ building.name }}</div>
                    <div class="od-map__callout-status">Processing {{ building.progress }}%</div>
                </div>
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useBuildingsStore } from 'src/stores/buildings';
import BuildingListItem from 'src/components/BuildingListItem.vue';

const router = useRouter();
const buildingsStore = useBuildingsStore();

const tab = ref<'list' | 'map'>('list');
const search = ref('');

const filteredBuildings = computed(() => {
    const term = search.value.toLowerCase();
    if (!term) return buildingsStore.buildings;
    return buildingsStore.buildings.filter((b) => b.name.toLowerCase().includes(term));
});

function openBuilding(id: string) {
    const building = buildingsStore.getById(id);
    if (building?.status === 'processing') {
        void router.push(`/capture/processing/${id}`);
    } else {
        void router.push(`/library/building/${id}`);
    }
}
</script>

<style scoped>
.fit {
    width: 100%;
    height: 100%;
    display: block;
}
</style>
