<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <section class="q-mb-lg">
            <h2 class="od-h-section q-mb-md">Quick Actions</h2>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-card flat bordered class="cursor-pointer" @click="$router.push('/capture')">
                        <q-card-section class="q-pa-md column">
                            <div class="od-icon-box">
                                <q-icon name="photo_camera" />
                            </div>
                            <div class="od-title q-mt-sm">New Capture</div>
                        </q-card-section>
                    </q-card>
                </div>
                <div class="col-6">
                    <q-card flat bordered class="cursor-pointer" @click="$router.push('/library')">
                        <q-card-section class="q-pa-md column">
                            <div class="od-icon-box">
                                <q-icon name="list" />
                            </div>
                            <div class="od-title q-mt-sm">Library</div>
                        </q-card-section>
                    </q-card>
                </div>
            </div>
        </section>

        <section v-if="buildingsStore.inProgressBuildings.length" class="q-mb-lg">
            <h2 class="od-h-section q-mb-md">In Progress</h2>
            <q-list class="od-list-flush">
                <building-list-item
                    v-for="building in buildingsStore.inProgressBuildings"
                    :key="building.id"
                    :building="building"
                    @click="openBuilding(building.id)"
                />
            </q-list>
        </section>

        <section>
            <h2 class="od-h-section q-mb-md">Recent</h2>
            <q-list class="od-list-flush">
                <building-list-item
                    v-for="building in buildingsStore.readyBuildings"
                    :key="building.id"
                    :building="building"
                    show-chevron
                    @click="openBuilding(building.id)"
                />
            </q-list>
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
