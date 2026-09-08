<template>
    <q-chip outline :color="presentation.color" :class="presentation.background">
        {{ label }}
        <q-tooltip v-if="reconstruction">Latest reconstruction attempt</q-tooltip>
    </q-chip>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ReconstructionStatus, ReconstructionSummary } from 'src/lib/buildings';

const props = defineProps<{ reconstruction: ReconstructionSummary | null }>();

const neutral = { color: 'grey-7', background: 'bg-grey-2' };
const active = { color: 'primary', background: 'bg-secondary' };
const failure = { color: 'negative', background: 'bg-red-1' };
const statuses = {
    preparing: { label: 'Preparing', ...active },
    scheduled: { label: 'Scheduled', ...active },
    running: { label: 'Processing', ...active },
    completed: { label: 'Completed', color: 'positive', background: 'bg-green-1' },
    failed: { label: 'Failed', ...failure },
    cancelled: { label: 'Cancelled', ...neutral },
    crashed: { label: 'Crashed', ...failure },
} satisfies Record<ReconstructionStatus, { label: string; color: string; background: string }>;

const presentation = computed(() =>
    props.reconstruction
        ? statuses[props.reconstruction.status]
        : { label: 'No reconstruction yet', ...neutral },
);
const label = computed(() =>
    props.reconstruction?.status === 'running'
        ? `Processing ${Math.round(props.reconstruction.progress * 100)}%`
        : presentation.value.label,
);
</script>
