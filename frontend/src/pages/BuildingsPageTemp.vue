<template>
    <q-page class="q-pa-md">
        <div class="page-content q-gutter-y-md">
            <div class="row items-center justify-between">
                <div>
                    <h1 class="text-h5 q-my-none">Buildings</h1>
                    <div class="text-caption text-grey-7">Buildings owned by the current user</div>
                </div>
                <q-btn
                    round
                    color="primary"
                    icon="add"
                    aria-label="New building"
                    to="/buildings/new"
                />
            </div>

            <q-banner v-if="errorMessage" rounded class="bg-red-1 text-negative">
                <div class="row items-center justify-between">
                    <span>{{ errorMessage }}</span>
                    <q-btn flat dense color="negative" label="Retry" @click="load" />
                </div>
            </q-banner>

            <q-card flat bordered>
                <q-card-section>
                    <div class="text-h6">Current user</div>
                </q-card-section>
                <q-separator />
                <q-card-section v-if="user" class="row q-col-gutter-md">
                    <div v-for="field in userFields" :key="field.label" class="col-12 col-sm-6">
                        <div class="text-caption text-grey-7">{{ field.label }}</div>
                        <div class="text-body2 selectable-text">{{ field.value }}</div>
                    </div>
                </q-card-section>
                <q-card-section v-else>
                    <q-skeleton v-for="index in 3" :key="index" type="text" />
                </q-card-section>
            </q-card>

            <div v-if="loading" class="row justify-center q-pa-xl">
                <q-spinner color="primary" size="3em" />
            </div>

            <q-card v-else-if="buildings.length === 0 && !errorMessage" flat bordered>
                <q-card-section class="column items-center q-pa-xl q-gutter-md">
                    <q-icon name="location_city" size="3rem" color="grey-5" />
                    <div class="text-grey-7">No buildings yet.</div>
                    <q-btn
                        color="primary"
                        icon="add"
                        label="Create a building"
                        to="/buildings/new"
                    />
                </q-card-section>
            </q-card>

            <div v-else class="row q-col-gutter-md">
                <div v-for="building in buildings" :key="building.id" class="col-12 col-sm-6">
                    <q-card
                        flat
                        bordered
                        class="building-card cursor-pointer"
                        @click="openBuilding(building.id)"
                    >
                        <q-card-section class="row items-center no-wrap">
                            <q-icon
                                name="location_city"
                                color="primary"
                                size="2rem"
                                class="q-mr-md"
                            />
                            <div class="col">
                                <div class="text-subtitle1 text-weight-medium">
                                    {{ building.name || 'Unnamed building' }}
                                </div>
                                <div class="text-caption text-grey-7">
                                    {{ formatCoordinates(building) }}
                                </div>
                            </div>
                            <q-icon name="chevron_right" color="grey-6" />
                        </q-card-section>
                    </q-card>
                </div>
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { type Building, type CurrentUser, getCurrentUser, listBuildings } from 'src/lib/buildings';

const router = useRouter();
const user = ref<CurrentUser | null>(null);
const buildings = ref<Building[]>([]);
const loading = ref(true);
const errorMessage = ref('');

const userFields = computed(() => [
    { label: 'ID', value: user.value?.id ?? '—' },
    { label: 'Name', value: user.value?.name || 'Not set' },
    { label: 'Username', value: user.value?.username || 'Not set' },
    { label: 'Email', value: user.value?.email || 'Not set' },
]);

async function load(): Promise<void> {
    loading.value = true;
    errorMessage.value = '';
    try {
        [user.value, buildings.value] = await Promise.all([getCurrentUser(), listBuildings()]);
    } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : String(error);
    } finally {
        loading.value = false;
    }
}

function formatCoordinates(building: Building): string {
    if (building.latitude === null || building.longitude === null) return 'Coordinates not set';
    return `${building.latitude.toFixed(6)}, ${building.longitude.toFixed(6)}`;
}

function openBuilding(buildingId: string): void {
    void router.push(`/buildings/${buildingId}`);
}

onMounted(load);
</script>

<style scoped>
.page-content {
    max-width: 900px;
    margin: 0 auto;
}
.building-card {
    transition: box-shadow 0.15s ease;
}
.building-card:hover {
    box-shadow: 0 3px 8px rgb(0 0 0 / 14%);
}
.selectable-text {
    user-select: text;
    overflow-wrap: anywhere;
}
</style>
