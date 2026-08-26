<template>
    <q-page class="od-page od-page--scroll">
        <section class="od-section">
            <h2 class="od-section-title">Quick Actions</h2>
            <div class="od-card-grid">
                <div class="od-card" tabindex="0" @click="$router.push('/capture')">
                    <div class="od-card__icon">
                        <q-icon name="photo_camera" />
                    </div>
                    <div class="od-card__title">New Capture</div>
                </div>
                <div class="od-card" tabindex="0" @click="$router.push('/library')">
                    <div class="od-card__icon">
                        <q-icon name="list" />
                    </div>
                    <div class="od-card__title">Library</div>
                </div>
            </div>
        </section>

        <section v-if="buildingsStore.inProgressBuildings.length" class="od-section">
            <h2 class="od-section-title">In Progress</h2>
            <div class="od-list od-list--flush">
                <building-list-item
                    v-for="building in buildingsStore.inProgressBuildings"
                    :key="building.id"
                    :building="building"
                    @click="openBuilding(building.id)"
                />
            </div>
        </section>

        <section class="od-section">
            <h2 class="od-section-title">Recent</h2>
            <div class="od-list od-list--flush">
                <building-list-item
                    v-for="building in buildingsStore.readyBuildings"
                    :key="building.id"
                    :building="building"
                    show-chevron
                    @click="openBuilding(building.id)"
                />
            </div>
        </section>
    </q-page>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useBuildingsStore } from 'src/stores/buildings';
import BuildingListItem from 'src/components/BuildingListItem.vue';

const router = useRouter();
const buildingsStore = useBuildingsStore();

function openBuilding(id: string) {
    const building = buildingsStore.getById(id);
    if (building?.status === 'processing') {
        void router.push(`/capture/processing/${id}`);
    } else {
        void router.push(`/library/building/${id}`);
    }
}
</script>
