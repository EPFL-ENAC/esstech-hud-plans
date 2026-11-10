<template>
    <query-state-switcher
        v-if="hasUpload"
        :state="state"
        :async-status="asyncStatus"
        :retry="refetch"
        :loading-message="t('uploads.loading')"
        :error-message="loadError"
    />

    <q-card v-if="upload || video" flat bordered class="upload-summary q-mb-xl">
        <q-card-section>
            <div class="text-weight-medium">{{ filename }}</div>
            <div class="text-caption text-grey-7">
                {{ formatFileSize(upload?.size_bytes ?? video?.size ?? 0, locale) }}
                <template v-if="upload"> · {{ t(`uploads.status.${upload.status}`) }} </template>
            </div>
            <div
                v-if="video && uploadState?.phase === 'uploading'"
                class="text-caption text-grey-7"
                role="status"
            >
                {{ t('uploads.new.starting') }}
            </div>
            <upload-transfer-progress
                v-if="upload?.status === 'pending' && uploadState?.phase !== 'failed'"
                class="q-mt-md"
                :progress="{ loaded: upload.uploaded_bytes, total: upload.size_bytes }"
                :resumed="false"
            />
        </q-card-section>
    </q-card>
    <p v-if="uploadState?.phase === 'failed'" class="text-negative" role="alert">
        {{ t('capture.draft.uploadFailed') }}
    </p>
    <p v-else-if="upload?.status === 'failed'" class="text-negative" role="alert">
        {{ t('reconstructions.fromUpload.failedUpload') }}
    </p>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import UploadTransferProgress from 'src/components/UploadTransferProgress.vue';
import { ApiError } from 'src/lib/api';
import type { CaptureDraft } from 'src/lib/captureDraftService';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import type { CaptureDraftUploadState } from 'src/queries/captureDrafts';
import { useUploadQuery } from 'src/queries/uploads';

const props = defineProps<{
    draft: CaptureDraft;
    uploadState?: CaptureDraftUploadState | undefined;
}>();
const { t, locale } = useI18n();
const source = computed(() => props.draft.source);
const uploadId = computed(() => ('uploadId' in source.value ? source.value.uploadId : ''));
const hasUpload = computed(() => uploadId.value !== '');
const video = computed(() => ('video' in source.value ? source.value.video : undefined));

const { data: upload, state, asyncStatus, isLoading, refetch } = useUploadQuery(uploadId);
const loadError = computed(() => {
    const error = state.value.error;
    return error instanceof ApiError && [404, 422].includes(error.status)
        ? t('reconstructions.fromUpload.unavailable')
        : t('reconstructions.fromUpload.loadFailed');
});
const filename = computed(
    () =>
        upload.value?.filename ??
        (video.value instanceof File ? video.value.name : t('capture.draft.video')),
);

defineExpose({ hasUpload, isLoading, refetch });
</script>

<style scoped>
.upload-summary {
    overflow-wrap: anywhere;
}
</style>
