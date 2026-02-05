<template>
    <q-page class="q-pa-md">
        <div class="wrapper">
            <h1 class="text-h5 q-mb-lg">Splat Generation Pipeline</h1>
            
            <!-- 1. Source Selection -->
            <q-card flat bordered class="q-pa-md q-mb-md">
                <div class="text-subtitle2 q-mb-sm text-primary">1. Input Video</div>
                <q-file
                    v-model="selectedFile"
                    label="Select video source"
                    filled
                    clearable
                    accept="video/*"
                    @update:model-value="handleFileChange"
                >
                    <template v-slot:prepend>
                        <q-icon name="movie" />
                    </template>
                </q-file>

                <!-- Video Preview Section -->
                <div v-if="videoPreviewUrl" class="q-mt-md overflow-hidden rounded-borders border-grey">
                    <div class="text-caption text-grey-7 q-mb-xs">Preview:</div>
                    <video 
                        :src="videoPreviewUrl" 
                        controls 
                        class="full-width rounded-borders shadow-2"
                        style="max-height: 300px; background: black;"
                    ></video>
                </div>
            </q-card>

            <!-- 2. Pipeline Stages -->
            <ffmpeg-settings v-model="ffmpegConfig" class="q-mb-md" />
            <colmap-settings v-model="colmapConfig" class="q-mb-md" />
            <brush-settings v-model="brushConfig" class="q-mb-md" />

            <!-- 3. Submission -->
            <div class="column items-center q-gutter-y-sm q-mt-xl">
                <q-btn 
                    size="lg"
                    color="primary" 
                    label="Launch Generation" 
                    icon="rocket_launch"
                    :loading="uploadStatus === 'Uploading...'"
                    :disabled="!selectedFile"
                    @click="uploadVideo"
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
import { onBeforeUnmount, ref } from "vue";
import { useRouter } from "vue-router";
import FfmpegSettings from "src/components/FfmpegSettings.vue";
import { makeDefaultFFMPEGConfig, type FFMPEGExtractionConfig } from "src/lib/splats/ffmpeg";
import ColmapSettings from "src/components/ColmapSettings.vue";
import { type ColmapConfig, makeAutoDefaults } from "src/lib/splats/colmap";
import BrushSettings from "src/components/BrushSettings.vue";
import { type BrushTrainingConfig, makeDefaultBrushConfig } from "src/lib/splats/brush";

const router = useRouter();

const selectedFile = ref<File | null>(null);
const videoPreviewUrl = ref<string | null>(null);

// Handling file selection and preview cleanup
const handleFileChange = (file: File | null) => {
    // Revoke old URL to prevent memory leaks
    if (videoPreviewUrl.value) {
        URL.revokeObjectURL(videoPreviewUrl.value);
        videoPreviewUrl.value = null;
    }

    if (file) {
        videoPreviewUrl.value = URL.createObjectURL(file);
    }
};

// Ensure cleanup if component is unmounted
onBeforeUnmount(() => {
    if (videoPreviewUrl.value) {
        URL.revokeObjectURL(videoPreviewUrl.value);
    }
});

const ffmpegConfig = ref<FFMPEGExtractionConfig>(makeDefaultFFMPEGConfig());
const colmapConfig = ref<ColmapConfig>(makeAutoDefaults());
const brushConfig = ref<BrushTrainingConfig>(makeDefaultBrushConfig());
const uploadStatus = ref("");
const statusClass = ref("");

const uploadVideo = async () => {
    if (!selectedFile.value) return;

    const formData = new FormData();
    // 1. Append the file
    formData.append("file", selectedFile.value);

    // 2. Append the settings as JSON strings
    // This allows the backend to receive the full pipeline configuration
    formData.append("ffmpeg_config", JSON.stringify(ffmpegConfig.value));
    formData.append("colmap_config", JSON.stringify(colmapConfig.value));
    formData.append("brush_config", JSON.stringify(brushConfig.value));

    try {
        uploadStatus.value = "Starting pipeline...";
        statusClass.value = "info";

        const response = await fetch("http://localhost:8000/splats/generate", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || "Processing failed");
        }

        const result = await response.json();
        uploadStatus.value = `Success: Generation ${result.generation_id} started`;
        statusClass.value = "success";
        
        return router.push(`/splat/${result.generation_id}`);
    } catch (error) {
        uploadStatus.value = "Error: " + (error as Error).message;
        statusClass.value = "error";
    }
};
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
</style>