<template>
    <q-page
        class="bg-white text-dark q-px-md q-pb-xl"
        style="padding-top: 64px"
        :aria-busy="isLoading"
    >
        <page-header :title="building && !notFound ? buildingName : 'Building'" />

        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <div v-if="state.status === 'pending'" role="status" aria-label="Loading building">
            <q-skeleton type="text" width="60%" class="q-mb-md" />
            <div class="row q-gutter-sm q-mb-lg">
                <q-skeleton type="QChip" />
                <q-skeleton type="QChip" />
            </div>
            <q-skeleton height="160px" square />
        </div>

        <template v-else-if="building && !notFound">
            <div v-if="isLoading" class="text-grey-7 q-mb-sm" role="status">
                <q-spinner color="primary" class="q-mr-sm" />
                Refreshing building…
            </div>

            <section class="q-mb-lg">
                <h1 class="building-name text-h6 text-weight-bold q-mt-none">
                    {{ buildingName }}
                </h1>
                <p v-if="building.address" class="building-name">{{ building.address }}</p>
                <div
                    v-if="building.latitude !== null && building.longitude !== null"
                    class="row wrap items-center q-gutter-sm"
                >
                    <q-chip outline color="primary" class="bg-teal-1">
                        Latitude: {{ building.latitude.toFixed(6) }}
                    </q-chip>
                    <q-chip outline color="primary" class="bg-teal-1">
                        Longitude: {{ building.longitude.toFixed(6) }}
                    </q-chip>
                </div>
                <p v-else class="text-grey-7">Coordinates not set</p>
                <building-location-map
                    class="q-my-md"
                    :latitude="building.latitude"
                    :longitude="building.longitude"
                />

                <q-btn
                    label="Edit"
                    icon="edit"
                    color="primary"
                    class="full-width q-mb-md"
                    unelevated
                    no-caps
                    @click="$router.push(`/building/${buildingId}/data`)"
                />
            </section>

            <building-reconstructions :key="buildingId" :building-id="buildingId" />
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import BuildingReconstructions from 'src/components/BuildingReconstructions.vue';
import BuildingLocationMap from 'src/components/BuildingLocationMap.vue';
import { ApiError } from 'src/lib/buildings';
import { useBuildingQuery } from 'src/queries/buildings';

const route = useRoute();
const buildingId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''));
const { data: building, state, asyncStatus, refetch } = useBuildingQuery(buildingId);
const buildingName = computed(() => building.value?.name.trim() || 'Untitled building');
const isLoading = computed(() => asyncStatus.value === 'loading');
const notFound = computed(
    () => state.value.error instanceof ApiError && state.value.error.status === 404,
);
const errorMessage = computed(() =>
    notFound.value
        ? 'Building not found.'
        : building.value
          ? 'Could not refresh this building.'
          : 'Could not load this building.',
);
</script>

<style scoped>
.building-name {
    overflow-wrap: anywhere;
}
</style>
