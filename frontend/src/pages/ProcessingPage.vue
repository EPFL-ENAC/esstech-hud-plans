<template>
    <q-page
        class="bg-white text-dark q-px-md"
        style="padding-top: 64px; display: flex; flex-direction: column; align-items: center"
    >
        <page-header :title="t('reconstructions.status.running')" />

        <div class="column items-center text-center q-mt-lg">
            <q-circular-progress
                show-value
                :value="building?.progress ?? 0"
                size="140px"
                :thickness="0.08"
                color="primary"
                track-color="grey-3"
            >
                <span class="text-h4 text-primary text-weight-medium">
                    {{ building?.progress ?? 0 }}%
                </span>
            </q-circular-progress>

            <h1 class="text-h6 text-weight-bold q-mb-sm q-mt-lg">
                {{ t('processing.title', { name: building?.name ?? t('buildings.title') }) }}
            </h1>
            <p class="text-body2 text-grey-6 q-mb-xl">{{ uploadedSize }} / {{ totalSize }}</p>

            <q-btn
                :label="t('processing.cancelButton')"
                outline
                color="negative"
                class="full-width q-mb-md"
                unelevated
                no-caps
                @click="confirmCancel"
            />

            <q-banner rounded class="bg-secondary text-primary text-left q-pa-md">
                {{ t('processing.notice') }}
            </q-banner>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useBuildingsStore } from 'src/stores/buildings';
import PageHeader from 'src/components/PageHeader.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

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
                message: t('processing.ready', { name: current.name }),
                position: 'top',
            });
            void router.replace(`/building/${current.id}`);
        }
    }, 1200);
}

function confirmCancel() {
    const name = building.value?.name ?? t('processing.thisCapture');
    $q.dialog({
        title: t('processing.cancelTitle'),
        message: t('processing.cancelConfirmation', { name }),
        cancel: true,
        persistent: true,
    }).onOk(() => {
        buildingsStore.remove(buildingId.value);
        $q.notify({
            type: 'warning',
            message: t('processing.cancelled'),
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
