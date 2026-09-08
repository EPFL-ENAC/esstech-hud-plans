<template>
    <q-form class="q-gutter-y-md" @submit="submit">
        <slot name="before" />

        <q-file v-model="videoFile" outlined accept="video/*" label="Video file" clearable>
            <template #prepend><q-icon name="movie" /></template>
        </q-file>

        <reconstruction-settings v-model="settings" />

        <q-btn
            color="primary"
            icon="upload"
            :label="submitLabel"
            type="submit"
            :disable="!canSubmit || loading"
            :loading="loading"
        />
    </q-form>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import type { ReconstructionSubmission } from 'src/lib/buildings';
import {
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';

withDefaults(defineProps<{ loading?: boolean; submitLabel?: string }>(), {
    loading: false,
    submitLabel: 'Submit reconstruction',
});

const emit = defineEmits<{ submit: [submission: ReconstructionSubmission] }>();
const videoFile = ref<File | null>(null);
const settings = ref(makeDefaultReconstructionSettings());
const canSubmit = computed(
    () => videoFile.value !== null && isValidReconstructionSettings(settings.value),
);

function submit(): void {
    if (!videoFile.value || !canSubmit.value) return;
    emit('submit', {
        video: videoFile.value,
        settings: toSplatGenerationSettings(settings.value),
    });
}
</script>
