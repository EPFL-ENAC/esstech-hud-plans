<template>
    <div class="file-picker-button">
        <input
            ref="input"
            type="file"
            hidden
            :accept="accept"
            :disabled="disable"
            @change="onFileChange"
        />
        <q-btn
            class="picker-button"
            color="primary"
            outline
            no-caps
            icon="upload_file"
            :label="t(file ? 'capture.video.pickAnotherFile' : 'capture.video.pickFile')"
            :disable="disable"
            @click="input?.click()"
        />
    </div>
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';

defineProps<{ accept: string; disable?: boolean }>();
const file = defineModel<File | null>({ required: true });
const input = useTemplateRef<HTMLInputElement>('input');
const { t } = useI18n();

function onFileChange(event: Event): void {
    const target = event.target as HTMLInputElement;
    const selectedFile = target.files?.[0];
    if (selectedFile) file.value = selectedFile;
    target.value = '';
}
</script>

<style scoped>
.file-picker-button {
    display: flex;
    min-width: 0;
}

.picker-button {
    width: 100%;
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}
</style>
