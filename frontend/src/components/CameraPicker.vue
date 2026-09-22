<template>
    <div
        v-if="cameras.length"
        class="camera-picker"
        :class="{ 'camera-picker--fullscreen': fullscreen }"
    >
        <q-btn
            v-if="hasBothSides"
            round
            flat
            icon="flip_camera_ios"
            :aria-label="switchLabel"
            :disable="disabled"
            @click="emit('selectSide', nextSide)"
        >
            <q-tooltip>{{ switchLabel }}</q-tooltip>
        </q-btn>

        <div v-if="sideCameras.length" class="camera-picker-options">
            <q-btn-toggle
                v-if="fullscreen"
                :model-value="selectedCameraId"
                :options="sideCameras"
                :disable="disabled"
                :aria-label="t('capture.camera.label')"
                color="grey-9"
                text-color="white"
                toggle-color="primary"
                unelevated
                no-caps
                no-wrap
                @update:model-value="emit('selectCamera', $event)"
            />
            <q-select
                v-else
                :model-value="selectedCameraId"
                :options="sideCameras"
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

        <q-btn-dropdown
            v-if="unknownCameras.length || returnSide"
            auto-close
            flat
            no-caps
            :label="fullscreen ? undefined : t('capture.camera.otherCameras')"
            :aria-label="t('capture.camera.otherCameras')"
            icon="more_horiz"
            :content-class="fullscreen ? 'bg-grey-10 text-white' : undefined"
            :disable="disabled"
        >
            <q-list :dark="fullscreen">
                <q-item-label header>{{ t('capture.camera.otherCameras') }}</q-item-label>
                <q-item
                    v-if="returnSide"
                    clickable
                    :disable="disabled"
                    @click="emit('selectSide', returnSide)"
                >
                    <q-item-section>
                        {{
                            t(
                                returnSide === 'front'
                                    ? 'capture.camera.front'
                                    : 'capture.camera.rear',
                            )
                        }}
                    </q-item-section>
                </q-item>
                <q-item
                    v-for="camera in unknownCameras"
                    :key="camera.value"
                    clickable
                    :active="camera.value === selectedCameraId"
                    :aria-current="camera.value === selectedCameraId ? 'true' : undefined"
                    :disable="disabled"
                    @click="emit('selectCamera', camera.value)"
                >
                    <q-item-section>{{ camera.label }}</q-item-section>
                    <q-item-section v-if="camera.value === selectedCameraId" side>
                        <q-icon name="check" />
                    </q-item-section>
                </q-item>
            </q-list>
        </q-btn-dropdown>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { CameraOption, CameraSide } from 'src/lib/cameras';

const props = withDefaults(
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
    selectSide: [side: CameraSide];
}>();

const { t } = useI18n();
const selectedSide = computed(
    () => props.cameras.find((camera) => camera.value === props.selectedCameraId)?.side ?? null,
);
const sideCameras = computed(() =>
    props.cameras.filter(
        (camera) => selectedSide.value !== null && camera.side === selectedSide.value,
    ),
);
const unknownCameras = computed(() => props.cameras.filter((camera) => camera.side === null));
const availableSides = computed(() =>
    (['front', 'rear'] as const).filter((side) =>
        props.cameras.some((camera) => camera.side === side),
    ),
);
const hasBothSides = computed(() => availableSides.value.length === 2);
const nextSide = computed<CameraSide>(() => (selectedSide.value === 'rear' ? 'front' : 'rear'));
const returnSide = computed(() =>
    selectedSide.value === null && availableSides.value.length === 1
        ? availableSides.value[0]
        : null,
);
const switchLabel = computed(() =>
    t(nextSide.value === 'front' ? 'capture.camera.switchToFront' : 'capture.camera.switchToRear'),
);
</script>

<style scoped>
.camera-picker {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
}

.camera-picker > .q-btn {
    flex-shrink: 0;
}

.camera-picker-options {
    flex: 1;
    min-width: 0;
    overflow-x: auto;
}

.camera-picker--fullscreen {
    padding: 8px 16px;
    color: white;
}

.camera-picker-options :deep(.q-btn-toggle) {
    display: flex;
    flex-wrap: nowrap;
    width: max-content;
    margin-inline: auto;
}
</style>
