<template>
    <q-chip outline :color="presentation.color" :class="presentation.background">
        <q-spinner v-if="isProcessing" size="1rem" class="q-mr-md" />
        {{ label }}
        <q-tooltip v-if="reconstruction && resolvedTooltip">{{ resolvedTooltip }}</q-tooltip>
    </q-chip>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ReconstructionStatus, ReconstructionSummary } from 'src/lib/buildings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const props = defineProps<{ reconstruction: ReconstructionSummary | null; tooltip?: string }>();
const resolvedTooltip = computed(() => props.tooltip ?? t('reconstructions.latestAttempt'));

const neutral = { color: 'grey-7', background: 'bg-grey-2' };
const active = { color: 'primary', background: 'bg-secondary' };
const failure = { color: 'negative', background: 'bg-red-1' };
const statuses = computed(
    () =>
        ({
            preparing: { label: t('reconstructions.status.preparing'), ...active },
            scheduled: { label: t('reconstructions.status.scheduled'), ...active },
            running: { label: t('reconstructions.status.running'), ...active },
            completed: {
                label: t('reconstructions.status.completed'),
                color: 'positive',
                background: 'bg-green-1',
            },
            failed: { label: t('reconstructions.status.failed'), ...failure },
            cancelled: { label: t('reconstructions.status.cancelled'), ...neutral },
            crashed: { label: t('reconstructions.status.crashed'), ...failure },
        }) satisfies Record<
            ReconstructionStatus,
            { label: string; color: string; background: string }
        >,
);

const isProcessing = computed(() =>
    ['preparing', 'scheduled', 'running'].includes(props.reconstruction?.status ?? ''),
);

const presentation = computed(() =>
    props.reconstruction
        ? statuses.value[props.reconstruction.status]
        : { label: t('reconstructions.noReconstruction'), ...neutral },
);
const label = computed(() =>
    props.reconstruction?.status === 'running'
        ? t('reconstructions.processingProgress', {
              progress: Math.round(props.reconstruction.progress * 100),
          })
        : presentation.value.label,
);
</script>
