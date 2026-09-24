<template>
    <q-page class="bg-white text-dark q-pb-xl" style="padding-top: 64px">
        <page-header :title="building && !notFound ? buildingName : t('buildings.title')" />

        <QueryStateSwitcher
            class="building-query"
            :state="state"
            :async-status="asyncStatus"
            :retry="refetch"
            :loading-message="t('buildings.loading')"
            :error-message="errorMessage"
        >
            <template #pending>
                <div class="q-px-md" aria-hidden="true">
                    <q-skeleton type="text" width="60%" class="q-mb-md" />
                    <div class="row q-gutter-sm q-mb-lg">
                        <q-skeleton type="QChip" />
                        <q-skeleton type="QChip" />
                    </div>
                    <q-skeleton height="160px" square />
                </div>
            </template>
            <template #refreshing>
                <div class="q-px-md text-grey-7">
                    <q-spinner color="primary" class="q-mr-sm" />
                    {{ t('buildings.refreshing') }}
                </div>
            </template>
            <template #success="{ data: building }">
                <template v-if="!notFound">
                    <section class="q-mb-lg q-px-md">
                        <q-expansion-item
                            :label="t('buildings.buildingInformation')"
                            icon="info"
                            expand-separator
                            class="building-info"
                        >
                            <div class="q-pa-md">
                                <p v-if="building.address" class="building-address">
                                    {{ building.address }}
                                </p>
                                <div
                                    v-if="building.latitude !== null && building.longitude !== null"
                                    class="row wrap items-center q-gutter-sm"
                                >
                                    <q-chip outline color="primary" class="bg-teal-1">
                                        {{
                                            t('buildings.latitude', {
                                                latitude: building.latitude.toFixed(6),
                                            })
                                        }}
                                    </q-chip>
                                    <q-chip outline color="primary" class="bg-teal-1">
                                        {{
                                            t('buildings.longitude', {
                                                longitude: building.longitude.toFixed(6),
                                            })
                                        }}
                                    </q-chip>
                                </div>
                                <p v-else class="text-grey-7">
                                    {{ t('buildings.coordinatesNotSet') }}
                                </p>
                                <building-location-map
                                    class="q-my-md"
                                    :latitude="building.latitude"
                                    :longitude="building.longitude"
                                />

                                <q-btn
                                    :label="t('common.edit')"
                                    icon="edit"
                                    color="primary"
                                    class="full-width"
                                    unelevated
                                    no-caps
                                    @click="$router.push(`/building/${buildingId}/data`)"
                                />
                            </div>
                        </q-expansion-item>
                    </section>

                    <building-reconstructions :key="buildingId" :building-id="buildingId" />
                </template>
            </template>
        </QueryStateSwitcher>
    </q-page>
</template>

<script setup lang="ts">
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import BuildingReconstructions from 'src/components/BuildingReconstructions.vue';
import BuildingLocationMap from 'src/components/BuildingLocationMap.vue';
import { ApiError } from 'src/lib/buildings';
import { useBuildingQuery } from 'src/queries/buildings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const route = useRoute();
const buildingId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''));
const { data: building, state, asyncStatus, refetch } = useBuildingQuery(buildingId);
const buildingName = computed(() => building.value?.name.trim() || t('buildings.untitled'));
const notFound = computed(
    () => state.value.error instanceof ApiError && state.value.error.status === 404,
);
const errorMessage = computed(() =>
    notFound.value
        ? t('buildings.notFound')
        : building.value
          ? t('buildings.refreshFailed')
          : t('buildings.loadFailed'),
);
</script>

<style scoped>
.building-query :deep(.query-error) {
    margin-inline: 1rem;
}

.building-address {
    overflow-wrap: anywhere;
    margin-top: 0;
}

/* Folded panel with the light grey border used by list separators elsewhere. */
.building-info {
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 4px;
    overflow: hidden;
}
</style>
