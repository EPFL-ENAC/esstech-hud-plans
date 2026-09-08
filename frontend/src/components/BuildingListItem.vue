<template>
    <q-item clickable @click="emit('click')">
        <q-item-section avatar>
            <q-avatar square size="72px" color="white" text-color="primary" class="avatar-icon">
                <floor-plan-thumb />
            </q-avatar>
        </q-item-section>

        <q-item-section>
            <q-item-label class="text-subtitle1 text-weight-medium">
                {{ building.name }}
            </q-item-label>
            <q-item-label caption>recorded {{ building.recordedDate }}</q-item-label>
            <q-item-label>
                <q-chip
                    v-if="building.status === 'processing'"
                    outline
                    color="negative"
                    class="bg-red-1"
                >
                    Processing {{ building.progress }}%
                </q-chip>
                <q-chip v-else outline color="primary" class="bg-secondary">ready</q-chip>
            </q-item-label>
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
