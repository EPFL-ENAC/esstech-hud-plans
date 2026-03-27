<template>
    <q-page class="q-pa-md">
        <div class="wrapper">
            <h1 class="text-h5 q-mb-lg">Admin</h1>

            <div class="column items-start q-gutter-y-sm">
                <q-btn
                    size="lg"
                    color="primary"
                    label="Download parameters table"
                    icon="table_chart"
                    :loading="downloading"
                    :disabled="downloading"
                    @click="downloadParametersTable"
                    class="full-width"
                />

                <div v-if="message" :class="messageClass" class="text-weight-bold">
                    <q-spinner-dots v-if="messageClass === 'info'" size="sm" class="q-mr-xs" />
                    {{ message }}
                </div>
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { baseUrl } from 'boot/api';

const downloading = ref(false);
const message = ref('');
const messageClass = ref('');

async function downloadParametersTable() {
    downloading.value = true;
    message.value = '';
    messageClass.value = 'info';

    try {
        const response = await fetch(`${baseUrl}/admin/parameters-table`, {
            method: 'GET',
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Download failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;

        const contentDisposition = response.headers.get('Content-Disposition');
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
            if (filenameMatch && filenameMatch[1]) {
                link.download = filenameMatch[1];
            } else {
                link.download = 'parameters_table.xlsx';
            }
        } else {
            link.download = 'parameters_table.xlsx';
        }

        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);

        message.value = 'Download started successfully';
        messageClass.value = 'success';
    } catch (error) {
        message.value = 'Error: ' + (error as Error).message;
        messageClass.value = 'error';
    } finally {
        downloading.value = false;
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
    cursor: pointer;
}
</style>
