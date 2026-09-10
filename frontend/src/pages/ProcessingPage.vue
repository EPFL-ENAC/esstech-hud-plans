<template>
    <q-page
        class="bg-white text-dark q-px-md"
        style="padding-top: 64px; display: flex; flex-direction: column; align-items: center"
    >
        <page-header :title="t('reconstructions.status.running')" />

        <div class="column items-center text-center q-mt-lg">
            <q-circular-progress
                show-value
                :value="percentage"
                size="140px"
                :thickness="0.08"
                :color="isFailureState ? 'negative' : 'primary'"
                track-color="grey-3"
            >
                <span
                    class="text-h4 text-weight-medium"
                    :class="isFailureState ? 'text-negative' : 'text-primary'"
                >
                    {{ percentage }}%
                </span>
            </q-circular-progress>

            <h1 class="text-h6 text-weight-bold q-mb-sm q-mt-lg">{{ chipMessage }}</h1>

            <q-btn
                v-if="!isFailureState"
                :label="t('processing.cancelButton')"
                outline
                color="negative"
                class="full-width q-mb-md"
                unelevated
                no-caps
                @click="confirmCancel"
            />

            <q-banner
                v-if="isFailureState"
                rounded
                class="bg-negative text-white text-left q-pa-md"
            >
                {{ reconstruction?.error_message ?? t('processing.notice') }}
            </q-banner>
            <q-banner v-else rounded class="bg-secondary text-primary text-left q-pa-md">
                {{ t('processing.notice') }}
            </q-banner>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import type { ReconstructionSummary } from 'src/lib/buildings';
import { cancelReconstruction } from 'src/lib/buildings';
import {
    RECONSTRUCTIONS_PAGE_SIZE,
    useReconstructionsQuery,
    useReconstructionStepQuery,
} from 'src/queries/reconstructions';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const route = useRoute();
const router = useRouter();
const $q = useQuasar();

const buildingId = computed(() => route.params.id as string);
const requestedReconstructionId = computed(() => route.query.reconstruction as string | null);
const offset = ref(0);
const { data } = useReconstructionsQuery(buildingId, offset);

// Same source as the status chips in the reconstruction list.
const reconstructions = computed(() => data.value?.slice(0, RECONSTRUCTIONS_PAGE_SIZE) ?? []);
function isProcessing(reconstruction: ReconstructionSummary): boolean {
    return ['preparing', 'scheduled', 'running'].includes(reconstruction.status);
}
const reconstruction = computed(() => {
    const list = reconstructions.value;
    // Prefer the reconstruction the user opened the drawer for, then any
    // active one, then the most recent row.
    const requested = requestedReconstructionId.value
        ? list.find(({ id }) => id === requestedReconstructionId.value)
        : undefined;
    return requested ?? list.find(isProcessing) ?? list[0];
});

const isFailureState = computed(
    () =>
        reconstruction.value !== undefined &&
        ['failed', 'cancelled', 'crashed'].includes(reconstruction.value.status),
);
const percentage = computed(() => Math.round((reconstruction.value?.progress ?? 0) * 100));
const reconstructionId = computed(() => reconstruction.value?.id ?? '');
const { data: currentStep } = useReconstructionStepQuery(buildingId, reconstructionId);
const currentStepDisplay = computed(() => {
    const step = currentStep.value;
    if (!step) return null;
    const words = step.split('-').join(' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
});
const chipMessage = computed(() => {
    const reconstructionValue = reconstruction.value;
    if (!reconstructionValue) {
        return t('reconstructions.noReconstruction');
    }
    if (reconstructionValue.status === 'running') {
        const step = currentStepDisplay.value;
        if (step) return step;
        return t('reconstructions.processingProgress', { progress: percentage.value });
    }
    return t(`reconstructions.status.${reconstructionValue.status}`);
});

function confirmCancel() {
    $q.dialog({
        title: t('processing.cancelTitle'),
        message: t('processing.cancelConfirmation', {
            name: t('reconstructions.named', {
                id: reconstruction.value?.id.slice(0, 8) ?? '',
            }),
        }),
        cancel: t('processing.cancelNo'),
        ok: t('processing.cancelYes'),
        persistent: true,
    }).onOk(() => {
        void confirmCancelProcessing();
    });
}

async function confirmCancelProcessing() {
    const reconstructionId = reconstruction.value?.id;
    if (!reconstructionId) return;

    try {
        await cancelReconstruction(buildingId.value, reconstructionId);
        $q.notify({
            type: 'positive',
            message: t('processing.cancelled'),
            position: 'top',
        });
        void router.replace(`/building/${buildingId.value}`);
    } catch {
        $q.notify({
            type: 'negative',
            message: t('processing.cancelFailed'),
            position: 'top',
        });
    }
}
</script>
