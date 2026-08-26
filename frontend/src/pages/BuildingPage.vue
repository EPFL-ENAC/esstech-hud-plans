<template>
    <q-page class="od-page od-page--scroll">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">{{ building?.name ?? 'Building' }}</div>
        </div>

        <div class="od-placeholder od-placeholder--video">Source Video</div>

        <div class="od-detail-meta">
            <span class="od-chip od-chip--primary">{{ building?.address }}</span>
            <span class="od-chip od-chip--primary">{{ building?.size }}</span>
            <span class="od-chip od-chip--primary">{{ building?.duration }}</span>
        </div>

        <p class="od-detail-description">{{ building?.description }}</p>

        <section class="od-section">
            <h2 class="od-section-title">Associated Plan</h2>
            <div class="od-list">
                <div
                    class="od-list-row"
                    tabindex="0"
                    @click="$router.push(`/library/building/${buildingId}/plan/2d`)"
                >
                    <div class="od-plan-card__icon">
                        <q-icon name="square" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-plan-card__title">2D Plan</div>
                        <div class="od-plan-card__subtitle">
                            Top-down floor plan with measurements and annotations
                        </div>
                    </div>
                    <q-icon name="chevron_right" class="od-list-row__chevron" />
                </div>

                <div
                    class="od-list-row"
                    tabindex="0"
                    @click="$router.push(`/library/building/${buildingId}/plan/3d`)"
                >
                    <div class="od-plan-card__icon">
                        <q-icon name="view_in_ar" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-plan-card__title">3D Plan</div>
                        <div class="od-plan-card__subtitle">
                            Interactive 3D model with orbit and export controls
                        </div>
                    </div>
                    <q-icon name="chevron_right" class="od-list-row__chevron" />
                </div>
            </div>
        </section>

        <q-btn
            label="Create Building Data and Report"
            color="primary"
            class="od-btn od-btn--primary full-width q-mb-md"
            unelevated
            no-caps
            @click="$router.push(`/library/building/${buildingId}/data`)"
        />

        <q-btn
            label="Delete Capture"
            outline
            class="od-btn od-btn--outline-negative full-width"
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
