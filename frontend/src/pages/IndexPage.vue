<template>
    <q-page class="row items-center justify-evenly">
        <div class="upload-container">
            <h2>Video Upload (Fetch API)</h2>
            <q-file
                v-model="selectedFile"
                label="Pick a video file"
                filled
                clearable
                accept="video/*"
            />
            <q-btn @click="uploadVideo" :disabled="!selectedFile">Upload</q-btn>

            <div v-if="uploadStatus" :class="statusClass">
                {{ uploadStatus }}
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();

const selectedFile = ref(null);
const uploadStatus = ref("");
const statusClass = ref("");

const uploadVideo = async () => {
    if (!selectedFile.value) return;

    const formData = new FormData();
    // The key "file" must match the parameter name in FastAPI: 
    // async def generate(file: UploadFile = File(...))
    formData.append("file", selectedFile.value);

    try {
        uploadStatus.value = "Uploading...";
        statusClass.value = "info";

        const response = await fetch("http://localhost:8000/splats/generate", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || "Upload failed");
        }

        const result = await response.json();
        uploadStatus.value = `Success: ${result.filename}`;
        statusClass.value = "success";
        
        return router.push(`/splat/${result.generation_id}`);
    } catch (error) {
        uploadStatus.value = "Error: " + (error as Error).message;
        statusClass.value = "error";
    }
};
</script>

<style scoped>
.upload-container {
    max-width: 400px;
    margin: 20px auto;
    padding: 20px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-family: sans-serif;
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