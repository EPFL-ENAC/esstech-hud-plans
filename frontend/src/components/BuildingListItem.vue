<template>
    <div class="od-list-row od-list-row--building" tabindex="0" @click="emit('click')">
        <div class="od-list-row__thumb">
            <floor-plan-thumb />
        </div>
        <div class="od-list-row__content">
            <div class="od-list-row__title">{{ building.name }}</div>
            <div class="od-list-row__meta">recorded {{ building.recordedDate }}</div>
            <div>
                <span v-if="building.status === 'processing'" class="od-chip od-chip--processing">
                    Processing {{ building.progress }}%
                </span>
                <span v-else class="od-chip od-chip--ready">ready</span>
            </div>
        </div>
        <q-icon v-if="showChevron" name="chevron_right" class="od-list-row__chevron" />
    </div>
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
