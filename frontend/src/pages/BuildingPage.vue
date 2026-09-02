<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="building?.name ?? 'Building'" />

        <q-card flat bordered square class="bg-grey-3 flex flex-center text-grey-7 q-mb-md">
            <div class="column items-center q-py-xl q-gutter-sm">
                <q-icon name="ondemand_video" size="48px" />
                <span>Source Video</span>
            </div>
        </q-card>

        <div class="row wrap items-center q-gutter-sm q-mb-md">
            <q-chip outline color="primary" class="bg-teal-1">{{ building?.address }}</q-chip>
            <q-chip outline color="primary" class="bg-teal-1">{{ building?.size }}</q-chip>
            <q-chip outline color="primary" class="bg-teal-1">{{ building?.duration }}</q-chip>
        </div>

        <p class="text-grey-6 q-mb-lg">{{ building?.description }}</p>

        <section class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-lg">Associated Plan</h2>
            <q-list class="q-gutter-y-md">
                <q-card
                    flat
                    bordered
                    clickable
                    @click="$router.push(`/library/building/${buildingId}/plan/2d`)"
                    class="q-py-sm"
                >
                    <q-item>
                        <q-item-section avatar>
                            <q-avatar
                                square
                                size="48px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <floor-plan-thumb />
                            </q-avatar>
                        </q-item-section>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium"
                                >2D Plan</q-item-label
                            >
                            <q-item-label caption
                                >Top-down floor plan with measurements and annotations</q-item-label
                            >
                        </q-item-section>
                        <q-item-section side>
                            <q-icon name="chevron_right" size="20px" color="dark" />
                        </q-item-section>
                    </q-item>
                </q-card>

                <q-card
                    flat
                    bordered
                    clickable
                    @click="$router.push(`/library/building/${buildingId}/plan/3d`)"
                    class="q-py-sm"
                >
                    <q-item>
                        <q-item-section avatar>
                            <q-avatar
                                square
                                size="48px"
                                font-size="31px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon name="view_in_ar" />
                            </q-avatar>
                        </q-item-section>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium"
                                >3D Plan</q-item-label
                            >
                            <q-item-label caption
                                >Interactive 3D model with orbit and export controls</q-item-label
                            >
                        </q-item-section>
                        <q-item-section side>
                            <q-icon name="chevron_right" size="20px" color="dark" />
                        </q-item-section>
                    </q-item>
                </q-card>
            </q-list>
        </section>

        <q-btn
            label="Create Building Data and Report"
            color="primary"
            class="full-width q-mb-md"
            unelevated
            no-caps
            @click="$router.push(`/library/building/${buildingId}/data`)"
        />

        <q-btn
            label="Delete Capture"
            outline
            color="negative"
            class="full-width"
            unelevated
            no-caps
            @click="confirmDelete"
        />
    </q-page>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useBuildingsStore } from 'src/stores/buildings';
import FloorPlanThumb from 'src/components/FloorPlanThumb.vue';
import PageHeader from 'src/components/PageHeader.vue';

const route = useRoute();
const router = useRouter();
const $q = useQuasar();
const buildingsStore = useBuildingsStore();

const buildingId = computed(() => route.params.id as string);
const building = computed(() => buildingsStore.getById(buildingId.value));

watchEffect(() => {
    if (building.value?.status === 'processing') {
        void router.replace(`/capture/processing/${buildingId.value}`);
    }
});

function confirmDelete() {
    $q.dialog({
        title: 'Delete capture',
        message: `Are you sure you want to delete ${building.value?.name ?? 'this capture'}?`,
        cancel: true,
        persistent: true,
    }).onOk(() => {
        buildingsStore.remove(buildingId.value);
        void router.push('/library');
    });
}
</script>
