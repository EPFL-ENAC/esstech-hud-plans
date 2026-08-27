<template>
    <q-page class="od-page od-page--scroll od-processing-page bg-white text-dark">
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
            <div class="od-topbar__title">Processing</div>
        </div>

        <div class="q-mt-lg" style="margin-bottom: 32px">
            <q-circular-progress
                show-value
                :value="building?.progress ?? 0"
                size="140px"
                :thickness="0.08"
                color="primary"
                track-color="grey-3"
            >
                <span class="od-processing-percent">{{ building?.progress ?? 0 }}%</span>
            </q-circular-progress>
        </div>

        <h1 class="od-h-section q-mb-sm">Processing - {{ building?.name ?? 'Building' }}</h1>
        <p class="od-processing-size" style="margin-bottom: 32px">
            {{ uploadedSize }} / {{ totalSize }}
        </p>

        <q-btn
            label="Cancel Processing"
            outline
            color="negative"
            class="od-btn full-width q-mb-md"
            unelevated
            no-caps
            @click="confirmCancel"
        />

        <div class="od-processing-info">
            Processing takes 10–60 min after upload. You'll receive a push notification when your
            plan is ready.
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useBuildingsStore } from 'src/stores/buildings';

const route = useRoute();
const router = useRouter();
const $q = useQuasar();
const buildingsStore = useBuildingsStore();

const buildingId = computed(() => route.params.id as string);
const building = computed(() => buildingsStore.getById(buildingId.value));

const totalSize = computed(() => building.value?.size ?? '0mb');
const totalMb = computed(() => parseInt(totalSize.value, 10) || 0);
const uploadedSize = computed(() => {
    const progress = building.value?.progress ?? 0;
    return `${Math.round((progress / 100) * totalMb.value)}mb`;
});

let intervalId: ReturnType<typeof setInterval> | null = null;

function startSimulation() {
    if (!building.value) return;

    intervalId = setInterval(() => {
        const current = building.value;
        if (!current) return;

        const next = Math.min(current.progress + Math.floor(Math.random() * 4) + 1, 100);
        buildingsStore.updateProgress(current.id, next);

        if (next >= 100) {
            buildingsStore.setStatus(current.id, 'ready');
            if (intervalId) {
                clearInterval(intervalId);
                intervalId = null;
            }
            $q.notify({
                type: 'positive',
                message: `${current.name} is ready.`,
                position: 'top',
            });
            void router.replace(`/library/building/${current.id}`);
        }
    }, 1200);
}

function confirmCancel() {
    const name = building.value?.name ?? 'this capture';
    $q.dialog({
        title: 'Cancel processing',
        message: `Are you sure you want to cancel processing for ${name}? The uploaded video will be deleted.`,
        cancel: true,
        persistent: true,
    }).onOk(() => {
        buildingsStore.remove(buildingId.value);
        $q.notify({
            type: 'warning',
            message: 'Processing cancelled.',
            position: 'top',
        });
        void router.replace('/library');
    });
}

onMounted(startSimulation);
onUnmounted(() => {
    if (intervalId) {
        clearInterval(intervalId);
    }
});
</script>
