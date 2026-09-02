<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header :back="false" title="Library">
            <q-btn
                flat
                no-caps
                color="primary"
                label="New Capture"
                @click="$router.push('/capture')"
            />
        </page-header>

        <q-tabs
            v-model="tab"
            no-caps
            indicator-color="primary"
            align="left"
            bordered
            class="q-mb-md"
        >
            <q-tab name="list" label="List" />
            <q-tab name="map" label="Map" />
        </q-tabs>

        <q-input v-model="search" outlined rounded placeholder="Search" class="q-mb-md">
            <template #prepend>
                <q-icon name="search" />
            </template>
        </q-input>

        <building-list v-if="tab === 'list'">
            <building-list-item
                v-for="building in filteredBuildings"
                :key="building.id"
                :building="building"
                :show-chevron="building.status === 'ready'"
                @click="openBuilding(building.id)"
            />
        </building-list>

        <q-card
            v-else
            flat
            bordered
            square
            class="bg-grey-3 relative-position"
            style="aspect-ratio: 3 / 4; overflow: hidden"
        >
            <svg viewBox="0 0 320 420" class="absolute-full" preserveAspectRatio="xMidYMid slice">
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
                class="absolute column items-center"
                :style="{
                    left: `${(building.x / 320) * 100}%`,
                    top: `${(building.y / 420) * 100}%`,
                    transform: 'translate(-50%, -50%)',
                    cursor: 'pointer',
                }"
                @click="openBuilding(building.id)"
            >
                <q-badge rounded color="primary" class="q-mb-xs">{{ building.name }}</q-badge>
                <q-icon name="place" color="primary" size="28px" />
                <q-badge
                    v-if="building.status === 'processing'"
                    rounded
                    outline
                    color="negative"
                    class="bg-red-1 q-mt-xs"
                >
                    Processing {{ building.progress }}%
                </q-badge>
            </div>
        </q-card>
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useBuildingsStore } from 'src/stores/buildings';
import BuildingListItem from 'src/components/BuildingListItem.vue';
import PageHeader from 'src/components/PageHeader.vue';
import BuildingList from 'src/components/BuildingList.vue';

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
