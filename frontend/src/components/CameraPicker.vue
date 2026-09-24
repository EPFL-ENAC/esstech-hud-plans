<template>
    <div
        v-if="cameras.length > 1"
        class="camera-picker"
        :class="{ 'camera-picker--fullscreen': fullscreen }"
    >
        <!-- Fullscreen recorder: one small numbered round button per camera. -->
        <template v-if="fullscreen">
            <q-btn
                v-for="(camera, index) in cameras"
                :key="camera.value"
                round
                class="camera-btn"
                :class="{ 'camera-btn--active': camera.value === selectedCameraId }"
                :label="String(index + 1)"
                :aria-label="camera.label"
                :aria-current="camera.value === selectedCameraId ? 'true' : undefined"
                :disable="disabled"
                @click="emit('selectCamera', camera.value)"
            >
                <q-tooltip>{{ camera.label }}</q-tooltip>
            </q-btn>
        </template>

        <!-- Embedded picker: one select listing every camera. -->
        <template v-else>
            <div class="camera-picker-options">
                <q-select
                    :model-value="selectedCameraId"
                    :options="cameras"
                    emit-value
                    map-options
                    outlined
                    :label="t('capture.camera.label')"
                    :aria-label="t('capture.camera.label')"
                    :disable="disabled"
                    :loading="loading"
                    @update:model-value="emit('selectCamera', $event)"
                >
                    <template #prepend><q-icon name="videocam" /></template>
                </q-select>
            </div>
        </template>
    </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import type { CameraOption } from 'src/lib/cameras';

withDefaults(
    defineProps<{
        cameras: CameraOption[];
        selectedCameraId: string | null;
        disabled: boolean;
        fullscreen?: boolean;
        loading?: boolean;
    }>(),
    { fullscreen: false, loading: false },
);

const emit = defineEmits<{
    selectCamera: [deviceId: string];
}>();

const { t } = useI18n();
</script>

<style scoped>
.camera-picker {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
}

.camera-picker-options {
    flex: 1;
    min-width: 0;
    overflow-x: auto;
}

/* Fullscreen strip: transparent container, buttons centered in the row. */
.camera-picker--fullscreen {
    justify-content: center;
    background: transparent;
    color: white;
}

/* Small transparent dark grey round buttons with white numbers, fixed
   so the label can never alter the circle shape. The active camera
   shows a lighter fill like the other record page buttons. QBtn ships
   em-based min-height and min-width (3em for round buttons), which
   must be zeroed or a 28px button renders as a tall oval. */
.camera-btn {
    flex-shrink: 0;
    width: 36px !important;
    height: 36px !important;
    padding: 0 !important;
    min-width: 0 !important;
    min-height: 0 !important;
    border-radius: 50% !important;
    color: #ffffff;
    background: rgba(85, 85, 85, 0.5);
}

.camera-btn--active {
    background: rgba(255, 255, 255, 0.25);
}
</style>
