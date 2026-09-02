<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl">
        <section class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-md">Quick Actions</h2>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-card flat bordered clickable @click="$router.push('/capture')">
                        <q-card-section class="column">
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon name="photo_camera" />
                            </q-avatar>
                            <div class="text-subtitle1 text-weight-medium q-mt-sm">New Capture</div>
                        </q-card-section>
                    </q-card>
                </div>
                <div class="col-6">
                    <q-card flat bordered clickable @click="$router.push('/library')">
                        <q-card-section class="column">
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon name="list" />
                            </q-avatar>
                            <div class="text-subtitle1 text-weight-medium q-mt-sm">Library</div>
                        </q-card-section>
                    </q-card>
                </div>
            </div>
        </section>

        <section v-if="buildingsStore.inProgressBuildings.length" class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-md">In Progress</h2>
            <building-list>
                <building-list-item
                    v-for="building in buildingsStore.inProgressBuildings"
                    :key="building.id"
                    :building="building"
                    @click="openBuilding(building.id)"
                />
            </building-list>
        </section>

        <section>
            <h2 class="text-h6 text-weight-bold q-mb-md">Recent</h2>
            <building-list>
                <building-list-item
                    v-for="building in buildingsStore.readyBuildings"
                    :key="building.id"
                    :building="building"
                    show-chevron
                    @click="openBuilding(building.id)"
                />
            </building-list>
        </section>
    </q-page>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useBuildingsStore } from 'src/stores/buildings';
import BuildingListItem from 'src/components/BuildingListItem.vue';
import BuildingList from 'src/components/BuildingList.vue';

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
