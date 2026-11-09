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
                :model-value="null"
                accept="video/*"
                @update:model-value="selectFile"
            />
            <q-btn
                outline
                no-caps
                color="primary"
                icon="videocam"
                :label="t('capture.video.takeVideo')"
                :to="{ name: 'capture-record', query: { buildingId: route.query.buildingId } }"
            />
        </section>

        <my-uploads-list ref="uploadsList" :activate="selectUpload">
            <template #action="{ upload }">
                <q-btn
                    v-if="upload.status !== 'failed'"
                    flat
                    no-caps
                    color="primary"
                    icon="add"
                    :label="$q.screen.lt.sm ? undefined : t('reconstructions.new')"
                    :aria-label="t('reconstructions.new')"
                    @click.stop="selectUpload(upload)"
                />
            </template>
        </my-uploads-list>
    </q-page>
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import MyUploadsList from 'src/components/MyUploadsList.vue';
import PageHeader from 'src/components/PageHeader.vue';
import type { UserUpload } from 'src/lib/uploads';
import { useCaptureDraftsStore, type CaptureDraftSource } from 'src/stores/captureDrafts';

const { t } = useI18n();
const router = useRouter();
const route = useRoute();
const { createDraft } = useCaptureDraftsStore();
const uploadsList = useTemplateRef<InstanceType<typeof MyUploadsList>>('uploadsList');

function openDraft(source: CaptureDraftSource): void {
    const draftId = createDraft(source);
    void router.push({
        name: 'capture-draft',
        params: { draftId },
        query: { buildingId: route.query.buildingId },
    });
}

function selectUpload(upload: UserUpload): void {
    openDraft({ uploadId: upload.id });
}

function selectFile(file: File | null): void {
    if (file) openDraft({ video: file });
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
</style>
