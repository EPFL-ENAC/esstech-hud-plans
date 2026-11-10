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
                :disable="busy"
                @update:model-value="selectFile"
            />
            <q-btn
                outline
                no-caps
                color="primary"
                icon="videocam"
                :label="t('capture.video.takeVideo')"
                :disable="busy"
                :to="{ name: 'capture-record', query: { buildingId: route.query.buildingId } }"
            />
            <q-banner v-if="errorMessage" class="full-width bg-red-1 text-negative" role="alert">
                {{ errorMessage }}
            </q-banner>
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
                    :disable="busy"
                    @click.stop="selectUpload(upload)"
                />
            </template>
        </my-uploads-list>
    </q-page>
</template>

<script setup lang="ts">
import { computed, useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import MyUploadsList from 'src/components/MyUploadsList.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { useRouteNavigation } from 'src/composables/useRouteNavigation';
import type { UserUpload } from 'src/lib/uploads';
import {
    useCreateCaptureDraftMutation,
    type CreateCaptureDraftSource,
} from 'src/mutations/captureDrafts';

const { t } = useI18n();
const route = useRoute();
const uploadsList = useTemplateRef<InstanceType<typeof MyUploadsList>>('uploadsList');
const { navigating, navigationFailed, clearNavigationFailure, push } = useRouteNavigation();
const { mutate, isLoading, error } = useCreateCaptureDraftMutation({
    onCreate(draftId) {
        void push({
            name: 'capture-draft',
            params: { draftId },
            query: { buildingId: route.query.buildingId },
        });
    },
});
const busy = computed(() => isLoading.value || navigating.value);
const errorMessage = computed(() => {
    if (navigationFailed.value) return t('capture.openFailed');
    return error.value ? t('capture.draft.createFailed') : '';
});

function selectSource(source: CreateCaptureDraftSource): void {
    if (busy.value) return;
    clearNavigationFailure();
    const buildingId = route.query.buildingId;
    mutate({ source, buildingId: typeof buildingId === 'string' ? buildingId : null });
}

function selectUpload(upload: UserUpload): void {
    selectSource({ uploadId: upload.id });
}

function selectFile(file: File | null): void {
    if (file) selectSource({ video: file });
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
