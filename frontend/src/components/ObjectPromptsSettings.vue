<script setup lang="ts">
import type { SpirulaObjectPromptsConfig } from 'src/lib/splats/spirula';

const props = defineProps<{
    label: string;
    selectLabel: string;
    hint: string;
    defaultPrompts: string[];
}>();

const config = defineModel<SpirulaObjectPromptsConfig>({ required: true });

const updateEnabled = (enabled: boolean) => {
    config.value.enabled = enabled;
    if (enabled && config.value.prompts.length === 0) {
        config.value.prompts = [...props.defaultPrompts];
    }
};
</script>

<template>
    <div>
        <q-toggle
            :model-value="config.enabled"
            :label="label"
            :aria-label="label"
            @update:model-value="updateEnabled"
        />
        <q-select
            v-model="config.prompts"
            class="q-mt-sm"
            outlined
            multiple
            use-chips
            use-input
            hide-dropdown-icon
            new-value-mode="add-unique"
            input-debounce="0"
            :disable="!config.enabled"
            :label="selectLabel"
            :aria-label="selectLabel"
            :hint="hint"
        />
    </div>
</template>
