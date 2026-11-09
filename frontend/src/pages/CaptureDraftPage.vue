<template>
    <q-page class="capture-draft-page">
        <page-header :title="t('reconstructions.new')">
            <q-btn
                v-if="uploadId"
                flat
                no-caps
                color="primary"
                icon="refresh"
                :label="t('uploads.refresh')"
                :disable="isLoading"
                @click="refetch()"
            />
        </page-header>

        <p v-if="loadStatus === 'loading'" role="status">{{ t('capture.draft.loading') }}</p>
        <q-banner v-else-if="loadStatus === 'error'" class="bg-red-1 text-negative" role="alert">
            {{ t('capture.draft.loadFailed') }}
            <template #action>
                <q-btn flat no-caps :label="t('common.retry')" @click="retryLoad" />
            </template>
        </q-banner>
        <div v-else-if="loadStatus === 'missing'">
            <p role="status">{{ t('capture.draft.unavailable') }}</p>
            <q-btn
                outline
                no-caps
                color="primary"
                :label="t('capture.newCapture')"
                :to="{ name: 'capture-new', query: { buildingId: route.query.buildingId } }"
            />
        </div>

        <query-state-switcher
            v-if="uploadId"
            :state="state"
            :async-status="asyncStatus"
            :retry="refetch"
            :loading-message="t('uploads.loading')"
            :error-message="loadError"
        />

        <template v-if="draft">
            <q-card v-if="upload || video" flat bordered class="upload-summary q-mb-xl">
                <q-card-section>
                    <div class="text-weight-medium">{{ filename }}</div>
                    <div class="text-caption text-grey-7">
                        {{ formatFileSize(upload?.size_bytes ?? video?.size ?? 0, locale) }}
                        <template v-if="upload">
                            · {{ t(`uploads.status.${upload.status}`) }}
                        </template>
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

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.destinationBuilding') }}</h2>
                <building-picker v-model="draft.form.buildingSelection" class="q-mb-md" />
            </section>

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.reconstructionSettings') }}</h2>
                <q-select
                    v-model="draft.form.preset"
                    outlined
                    :options="presetOptions"
                    emit-value
                    map-options
                    :label="t('capture.preset')"
                    class="q-mb-xl"
                />
                <section
                    v-if="draft.form.preset === 'advanced'"
                    class="q-mb-xl"
                    :aria-label="t('capture.advancedSettings')"
                >
                    <reconstruction-settings v-model="draft.form.advancedSettings" />
                    <p v-if="!hasValidSettings" class="text-negative q-mt-md" role="alert">
                        {{ t('capture.invalidSettings') }}
                    </p>
                </section>
            </section>

            <q-banner
                v-if="saveStatus === 'error'"
                class="bg-red-1 text-negative q-mb-md"
                role="alert"
            >
                {{ t('capture.draft.saveFailed') }}
                <template #action>
                    <q-btn flat no-caps :label="t('common.retry')" @click="retrySave" />
                </template>
            </q-banner>
            <p v-else class="text-caption text-grey-7" role="status">
                {{ t(saveStatus === 'saving' ? 'capture.draft.saving' : 'capture.draft.saved') }}
            </p>

            <q-btn
                :label="t('capture.startProcessing')"
                color="primary"
                class="full-width"
                unelevated
                no-caps
                disable
            />
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import PageHeader from 'src/components/PageHeader.vue';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import UploadTransferProgress from 'src/components/UploadTransferProgress.vue';
import { useCaptureDraft } from 'src/composables/useCaptureDraft';
import { ApiError } from 'src/lib/api';
import { isValidReconstructionSettings } from 'src/lib/reconstruction-settings';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { useUploadQuery } from 'src/queries/uploads';

const props = defineProps<{ draftId: string }>();
const { t, locale } = useI18n();
const route = useRoute();
const { draft, loadStatus, uploadState, saveStatus, retryLoad, retrySave } = useCaptureDraft(
    props.draftId,
);
const source = computed(() => draft.value?.source);
const uploadId = computed(() =>
    source.value && 'uploadId' in source.value ? source.value.uploadId : '',
);
const video = computed(() =>
    source.value && 'video' in source.value ? source.value.video : undefined,
);

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

const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const hasValidSettings = computed(
    () => draft.value && isValidReconstructionSettings(draft.value.form.advancedSettings),
);
</script>

<style scoped>
.capture-draft-page {
    padding: 64px 16px 48px;
    background: #fff;
    color: var(--q-dark);
}

.upload-summary {
    overflow-wrap: anywhere;
}
</style>
