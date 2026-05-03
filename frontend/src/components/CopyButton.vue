<script setup lang="ts">
import { copyToClipboard, useQuasar } from 'quasar';

interface Props {
    getText: () => string; // Function to get the text to copy
    message?: string; // Optional custom notification message
    label?: string; // Button text label
}

const props = withDefaults(defineProps<Props>(), {
    message: 'Copied to clipboard',
    label: '',
});

const $q = useQuasar();

async function copyText() {
    try {
        await copyToClipboard(props.getText());
        $q.notify({
            message: props.message,
            color: 'positive',
            icon: 'content_copy',
            timeout: 2000,
        });
    } catch (e) {
        console.error('Failed to copy text:', e);
        $q.notify({
            message: 'Failed to copy',
            color: 'negative',
        });
    }
}
</script>

<template>
    <q-btn v-bind="$attrs" icon="content_copy" :label="label" @click="copyText" />
</template>
