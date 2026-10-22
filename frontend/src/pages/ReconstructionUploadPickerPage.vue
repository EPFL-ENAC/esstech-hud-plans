<template>
    <q-page class="bg-white text-dark q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('reconstructions.fromUpload.title')">
            <q-btn
                flat
                no-caps
                color="primary"
                icon="refresh"
                :label="t('uploads.refresh')"
                :disable="uploadsList?.isLoading"
                @click="uploadsList?.refetch()"
            />
        </page-header>

        <section class="upload-actions q-pa-md">
            <file-picker-button
                :model-value="selectedFile"
                accept="video/*"
                :disable="busy || uploadId !== null"
                @update:model-value="selectFile"
            />
            <q-btn
                outline
                no-caps
                color="primary"
                icon="videocam"
                :label="t('capture.video.takeVideo')"
                :disable="busy || uploadId !== null"
                :to="{ name: 'record-reconstruction-upload' }"
            />
            <q-banner v-if="errorMessage" class="bg-red-1 text-negative upload-error" role="alert">
                {{ errorMessage }}
                <template #action>
                    <q-btn
                        flat
                        no-caps
                        :loading="busy"
                        :label="
                            t(uploadId ? 'reconstructions.fromUpload.openForm' : 'common.retry')
                        "
                        @click="retry"
                    />
                </template>
            </q-banner>
        </section>

        <my-uploads-list ref="uploadsList" :activate="openUpload">
            <template #action="{ upload }">
                <q-btn
                    v-if="upload.status !== 'failed'"
                    flat
                    no-caps
                    color="primary"
                    icon="add"
                    :label="$q.screen.lt.sm ? undefined : t('reconstructions.new')"
                    :aria-label="t('reconstructions.new')"
                    :to="{
                        name: 'reconstruction-from-upload',
                        params: { uploadId: upload.id },
                    }"
                    @click.stop
                />
            </template>
        </my-uploads-list>

        <loading-overlay v-if="busy" :message="t('reconstructions.fromUpload.starting')" />
    </q-page>
</template>

<script setup lang="ts">
import { shallowRef, useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import MyUploadsList from 'src/components/MyUploadsList.vue';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import LoadingOverlay from 'src/components/LoadingOverlay.vue';
import type { UserUpload } from 'src/lib/uploads';
import { useUploadForReconstruction } from 'src/composables/useUploadForReconstruction';

const { t } = useI18n();
const router = useRouter();
const uploadsList = useTemplateRef<InstanceType<typeof MyUploadsList>>('uploadsList');
const selectedFile = shallowRef<File | null>(null);
const { startUpload, retry, busy, uploadId, errorMessage } = useUploadForReconstruction();

function openUpload(upload: UserUpload): void {
    void router.push({
        name: 'reconstruction-from-upload',
        params: { uploadId: upload.id },
    });
}

function selectFile(file: File | null): void {
    if (!file || busy.value || uploadId.value !== null) return;
    selectedFile.value = file;
    startUpload(file);
}
</script>

<style scoped>
.upload-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.upload-actions > .file-picker-button,
.upload-actions > .q-btn {
    flex: 1 1 160px;
}

.upload-error {
    width: 100%;
}
</style>
