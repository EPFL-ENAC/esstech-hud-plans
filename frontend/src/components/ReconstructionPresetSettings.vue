<template>
    <h2 class="text-h6 text-weight-bold">{{ t('capture.reconstructionSettings') }}</h2>
    <q-select
        v-model="preset"
        outlined
        :options="presetOptions"
        emit-value
        map-options
        :label="t('capture.preset')"
        :disable="disablePreset"
        class="q-mb-xl"
    />
    <section
        v-if="preset === 'advanced'"
        class="q-mb-xl"
        :aria-label="t('capture.advancedSettings')"
    >
        <reconstruction-settings v-model="advancedSettings" />
        <p v-if="!isValid" class="text-negative q-mt-md" role="alert">
            {{ t('capture.invalidSettings') }}
        </p>
    </section>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import {
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
    isValidReconstructionSettings,
} from 'src/lib/reconstruction-settings';

defineProps<{ disablePreset?: boolean }>();
const emit = defineEmits<{ valid: [value: boolean] }>();
const preset = defineModel<ReconstructionPreset>('preset', { required: true });
const advancedSettings = defineModel<ReconstructionSettingsConfig>('advancedSettings', {
    required: true,
});

const { t } = useI18n();
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const isValid = computed(
    () => preset.value !== 'advanced' || isValidReconstructionSettings(advancedSettings.value),
);
watch(isValid, (value) => emit('valid', value), { immediate: true, flush: 'sync' });
</script>
