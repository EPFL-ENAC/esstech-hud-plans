<template>
    <q-page class="q-pa-md">
        <div class="wrapper">
            <h1 class="text-h5 q-mb-lg">Splat Generation Pipeline</h1>

            <input-settings v-model="inputConfig" v-model:tab="activeTab" class="q-mb-md" />
            <frame-extraction-settings
                v-model="frameExtractionConfig"
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
import { ref, type Ref, computed, onMounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import InputSettings from 'src/components/InputSettings.vue';
import { type InputConfig, makeDefaultInputConfig } from 'src/lib/splats/input';
import FrameExtractionSettings from 'src/components/FrameExtractionSettings.vue';
import {
    type FrameExtractionConfig,
    makeDefaultFrameExtractionConfig,
} from 'src/lib/splats/frameExtraction';
import ColmapSettings from 'src/components/ColmapSettings.vue';
import { type ColmapConfig, makeAutoDefaults } from 'src/lib/splats/colmap';
import BrushSettings from 'src/components/BrushSettings.vue';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from 'src/lib/splats/brush';
// import BlueprintSettings from 'src/components/BlueprintSettings.vue';
import { type BlueprintConfig, makeDefaultBlueprintConfig } from 'src/lib/splats/blueprint';
import { baseUrl } from 'boot/api';

const router = useRouter();
const route = useRoute();

const inputConfig: Ref<InputConfig> = ref(makeDefaultInputConfig());
const activeTab = ref<'video' | 'colmap'>('video');
const isInputConfigFilled = computed(() => {
    if (inputConfig.value.type === 'video') {
        return !!inputConfig.value.selectedVideoFile;
    } else {
        return !!inputConfig.value.colmapGenerationId;
    }
});
const frameExtractionConfig = ref<FrameExtractionConfig>(makeDefaultFrameExtractionConfig());
const colmapConfig = ref<ColmapConfig>(makeAutoDefaults());
const brushConfig = ref<BrushTrainingConfig>(makeDefaultBrushConfig());
const blueprintConfig = ref<BlueprintConfig>(makeDefaultBlueprintConfig());
const uploadStatus = ref('');
const statusClass = ref('');

onMounted(() => {
    const colmapGenerationId = route.query.colmapGenerationId as string | undefined;
    if (colmapGenerationId) {
        inputConfig.value.type = 'colmap';
        inputConfig.value.colmapGenerationId = colmapGenerationId;
        activeTab.value = 'colmap';
    }

    if (route.query.colmapSparseReconstructionId) {
        inputConfig.value.colmapSparseReconstructionId = Number(
            route.query.colmapSparseReconstructionId,
        );
    }

    if (route.query.brushTotalSteps) {
        brushConfig.value.totalSteps = Number(route.query.brushTotalSteps);
    }
    if (route.query.brushRenderMode) {
        brushConfig.value.renderMode = route.query.brushRenderMode as 'default' | 'mip';
    }
    if (route.query.brushShDegree) {
        brushConfig.value.shDegree = Number(route.query.brushShDegree);
    }
    if (route.query.brushMaxSplats) {
        brushConfig.value.maxSplats = Number(route.query.brushMaxSplats);
    }
    if (route.query.brushGrowthGradThreshold) {
        brushConfig.value.growthGradThreshold = Number(route.query.brushGrowthGradThreshold);
    }
    if (route.query.brushRefineEvery) {
        brushConfig.value.refineEvery = Number(route.query.brushRefineEvery);
    }
    if (route.query.brushGrowthStopIter) {
        brushConfig.value.growthStopIter = Number(route.query.brushGrowthStopIter);
    }
    if (route.query.brushAlphaMode) {
        brushConfig.value.alphaMode = route.query.brushAlphaMode as 'masked' | 'transparent';
    }
    if (route.query.brushMaxResolution) {
        brushConfig.value.maxResolution = Number(route.query.brushMaxResolution);
    }
    if (route.query.brushSubsampleFrames) {
        brushConfig.value.subsampleFrames = Number(route.query.brushSubsampleFrames);
    }
});

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
    formData.append('colmap_config', JSON.stringify(colmapConfig.value));
    formData.append('frame_extraction_config', JSON.stringify(frameExtractionConfig.value));
    formData.append('brush_config', JSON.stringify(brushConfig.value));
    // Only include blueprint config if enabled
    if (blueprintConfig.value.enabled) {
        formData.append('blueprint_config', JSON.stringify(blueprintConfig.value));
    }

    // Append device information
    formData.append('device_name', inputConfig.value.deviceName || '');
    formData.append('camera_type', inputConfig.value.cameraType);

    // Append browser info
    formData.append('browser_info', navigator.userAgent);

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
    if (inputConfig.value.colmapSparseReconstructionId !== undefined) {
        formData.append(
            'colmap_sparse_reconstruction_id',
            String(inputConfig.value.colmapSparseReconstructionId),
        );
    }
    formData.append('brush_config', JSON.stringify(brushConfig.value));
    formData.append('frame_extraction_config', JSON.stringify(frameExtractionConfig.value));
    if (blueprintConfig.value.enabled) {
        formData.append('blueprint_config', JSON.stringify(blueprintConfig.value));
    }

    // Append browser info
    formData.append('browser_info', navigator.userAgent);

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
