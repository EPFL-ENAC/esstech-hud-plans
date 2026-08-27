<template>
    <q-item class="od-row-building" clickable tabindex="0" @click="emit('click')">
        <q-item-section avatar>
            <div class="od-icon-box od-icon-box--lg">
                <floor-plan-thumb />
            </div>
        </q-item-section>

        <q-item-section class="q-gutter-y-xs">
            <div class="od-title">{{ building.name }}</div>
            <div class="od-subtitle">recorded {{ building.recordedDate }}</div>
            <div>
                <q-chip
                    v-if="building.status === 'processing'"
                    dense
                    outline
                    color="negative"
                    class="bg-negative-soft"
                >
                    Processing {{ building.progress }}%
                </q-chip>
                <q-chip v-else dense outline color="primary" class="bg-secondary">ready</q-chip>
            </div>
        </q-item-section>

        <q-item-section v-if="showChevron" side>
            <q-icon name="chevron_right" size="20px" color="dark" />
        </q-item-section>
    </q-item>
</template>

<script setup lang="ts">
import FloorPlanThumb from 'src/components/FloorPlanThumb.vue';
import type { Building } from 'src/stores/buildings';

interface Props {
    building: Building;
    showChevron?: boolean;
}

withDefaults(defineProps<Props>(), {
    showChevron: false,
});

const emit = defineEmits<{
    (e: 'click'): void;
}>();
</script>
