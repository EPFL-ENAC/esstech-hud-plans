<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                color="primary"
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">{{ building?.name ?? 'Building' }}</div>
        </div>

        <div class="od-placeholder">Source Video</div>

        <div class="row wrap items-center q-gutter-sm q-mb-md">
            <q-chip dense outline color="primary" class="bg-primary-soft">{{
                building?.address
            }}</q-chip>
            <q-chip dense outline color="primary" class="bg-primary-soft">{{
                building?.size
            }}</q-chip>
            <q-chip dense outline color="primary" class="bg-primary-soft">{{
                building?.duration
            }}</q-chip>
        </div>

        <p class="text-muted q-mb-lg">{{ building?.description }}</p>

        <section class="q-mb-lg">
            <h2 class="od-h-section q-mb-lg">Associated Plan</h2>
            <q-list class="q-gutter-y-md">
                <q-item
                    class="od-card-row"
                    clickable
                    tabindex="0"
                    @click="$router.push(`/library/building/${buildingId}/plan/2d`)"
                >
                    <q-item-section avatar>
                        <div class="od-icon-box">
                            <floor-plan-thumb />
                        </div>
                    </q-item-section>
                    <q-item-section class="q-gutter-y-xs">
                        <div class="od-title">2D Plan</div>
                        <div class="od-subtitle">
                            Top-down floor plan with measurements and annotations
                        </div>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>

                <q-item
                    class="od-card-row"
                    clickable
                    tabindex="0"
                    @click="$router.push(`/library/building/${buildingId}/plan/3d`)"
                >
                    <q-item-section avatar>
                        <div class="od-icon-box">
                            <q-icon name="view_in_ar" size="31px" />
                        </div>
                    </q-item-section>
                    <q-item-section class="q-gutter-y-xs">
                        <div class="od-title">3D Plan</div>
                        <div class="od-subtitle">
                            Interactive 3D model with orbit and export controls
                        </div>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-list>
        </section>

        <q-btn
            label="Create Building Data and Report"
            color="primary"
            class="od-btn full-width q-mb-md"
            unelevated
            no-caps
            @click="$router.push(`/library/building/${buildingId}/data`)"
        />

        <q-btn
            label="Delete Capture"
            outline
            color="negative"
            class="od-btn full-width"
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
