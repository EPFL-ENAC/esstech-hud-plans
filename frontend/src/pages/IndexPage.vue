<template>
    <q-page class="q-pa-md">
        <div class="wrapper">
            <h1 class="text-h5 q-mb-lg">Splat Generation Pipeline</h1>

            <!-- 1. Source Selection -->
            <input-settings
                :modelValue="inputConfig"
                @update:modelValue="inputConfig = $event"
                class="q-mb-md"
            />

            <!-- 2. Pipeline Stages -->
            <ffmpeg-settings
                v-model="ffmpegConfig"
                v-if="inputConfig.type === 'video'"
                class="q-mb-md"
            />
            <colmap-settings
                v-model="colmapConfig"
                v-if="inputConfig.type === 'video'"
                class="q-mb-md"
            />
            <brush-settings v-model="brushConfig" class="q-mb-md" />
            <!-- <blueprint-settings v-model="blueprintConfig" class="q-mb-md" /> -->

            <!-- 3. Submission -->
            <div class="column items-center q-gutter-y-sm q-mt-xl">
                <q-btn
                    size="lg"
                    color="primary"
                    label="Launch Generation"
                    icon="rocket_launch"
                    :loading="uploadStatus === 'Uploading...'"
                    :disabled="!isInputConfigFilled || uploadStatus === 'Uploading...'"
                    @click="submitJob"
                    class="full-width"
                />

                <div v-if="uploadStatus" :class="statusClass" class="text-weight-bold">
                    <q-spinner-dots v-if="statusClass === 'info'" size="sm" class="q-mr-xs" />
                    {{ uploadStatus }}
                </div>
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { ref, type Ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import InputSettings from 'src/components/InputSettings.vue';
import { type InputConfig, makeDefaultInputConfig } from 'src/lib/splats/input';
import FfmpegSettings from 'src/components/FfmpegSettings.vue';
import { type FFMPEGExtractionConfig, makeDefaultFFMPEGConfig } from 'src/lib/splats/ffmpeg';
import ColmapSettings from 'src/components/ColmapSettings.vue';
import { type ColmapConfig, makeAutoDefaults } from 'src/lib/splats/colmap';
import BrushSettings from 'src/components/BrushSettings.vue';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from 'src/lib/splats/brush';
// import BlueprintSettings from 'src/components/BlueprintSettings.vue';
import { type BlueprintConfig, makeDefaultBlueprintConfig } from 'src/lib/splats/blueprint';
import { baseUrl } from 'boot/api';

const router = useRouter();

const inputConfig: Ref<InputConfig> = ref(makeDefaultInputConfig());
const isInputConfigFilled = computed(() => {
    if (inputConfig.value.type === 'video') {
        return !!inputConfig.value.selectedVideoFile;
    } else {
        return !!inputConfig.value.colmapGenerationId;
    }
});
const ffmpegConfig = ref<FFMPEGExtractionConfig>(makeDefaultFFMPEGConfig());
const colmapConfig = ref<ColmapConfig>(makeAutoDefaults());
const brushConfig = ref<BrushTrainingConfig>(makeDefaultBrushConfig());
const blueprintConfig = ref<BlueprintConfig>(makeDefaultBlueprintConfig());
const uploadStatus = ref('');
const statusClass = ref('');

async function submitJob() {
    if (inputConfig.value.type === 'video') {
        await uploadVideo();
    } else {
        await restartBrush();
    }
}

async function uploadVideo() {
    if (!inputConfig.value.selectedVideoFile) return;

    const formData = new FormData();
    formData.append('file', inputConfig.value.selectedVideoFile);

    // 2. Append the settings as JSON strings
    // This allows the backend to receive the full pipeline configuration
    formData.append('ffmpeg_config', JSON.stringify(ffmpegConfig.value));
    formData.append('colmap_config', JSON.stringify(colmapConfig.value));
    formData.append('brush_config', JSON.stringify(brushConfig.value));
    // Only include blueprint config if enabled
    if (blueprintConfig.value.enabled) {
        formData.append('blueprint_config', JSON.stringify(blueprintConfig.value));
    }

    try {
        uploadStatus.value = 'Starting pipeline...';
        statusClass.value = 'info';

        const response = await fetch(`${baseUrl}/splats/generate`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Processing failed');
        }

        const result = await response.json();
        uploadStatus.value = `Success: Generation ${result.generation_id} started`;
        statusClass.value = 'success';

        return router.push(`/splat/${result.generation_id}`);
    } catch (error) {
        uploadStatus.value = 'Error: ' + (error as Error).message;
        statusClass.value = 'error';
    }
}

async function restartBrush() {
    if (!inputConfig.value.colmapGenerationId) return;

    const formData = new FormData();
    formData.append('colmap_generation_id', inputConfig.value.colmapGenerationId);
    formData.append('brush_config', JSON.stringify(brushConfig.value));
    if (blueprintConfig.value.enabled) {
        formData.append('blueprint_config', JSON.stringify(blueprintConfig.value));
    }

    try {
        uploadStatus.value = 'Starting brush restart...';
        statusClass.value = 'info';

        const response = await fetch(`${baseUrl}/splats/restart-brush`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Processing failed');
        }

        const result = await response.json();
        uploadStatus.value = `Success: Generation ${result.generation_id} started`;
        statusClass.value = 'success';

        return router.push(`/splat/${result.generation_id}`);
    } catch (error) {
        uploadStatus.value = 'Error: ' + (error as Error).message;
        statusClass.value = 'error';
    }
}
</script>

<style scoped>
.wrapper {
    max-width: 600px;
    margin: 0 auto;
}

.success {
    color: #2e7d32;
    margin-top: 10px;
}

.error {
    color: #d32f2f;
    margin-top: 10px;
}

.info {
    color: #1976d2;
    margin-top: 10px;
}

button {
    margin-left: 10px;
    cursor: pointer;
}

.text-subtitle2 {
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.75rem;
}
</style>
