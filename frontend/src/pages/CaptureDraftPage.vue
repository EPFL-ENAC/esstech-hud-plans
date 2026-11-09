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

        <div v-if="!draft">
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

        <template v-if="upload || video">
            <q-card flat bordered class="upload-summary q-mb-xl">
                <q-card-section>
                    <div class="text-weight-medium">{{ filename }}</div>
                    <div class="text-caption text-grey-7">
                        {{ formatFileSize(upload?.size_bytes ?? video?.size ?? 0, locale) }}
                        <template v-if="upload">
                            · {{ t(`uploads.status.${upload.status}`) }}
                        </template>
                    </div>
                    <upload-transfer-progress
                        v-if="upload?.status === 'pending'"
                        class="q-mt-md"
                        :progress="{ loaded: upload.uploaded_bytes, total: upload.size_bytes }"
                        :resumed="false"
                    />
                </q-card-section>
            </q-card>
            <p v-if="upload?.status === 'failed'" class="text-negative" role="alert">
                {{ t('reconstructions.fromUpload.failedUpload') }}
            </p>

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.destinationBuilding') }}</h2>
                <building-picker
                    v-model="buildingSelection"
                    :disable="upload?.status === 'failed'"
                    class="q-mb-md"
                />
            </section>

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.reconstructionSettings') }}</h2>
                <q-select
                    v-model="preset"
                    outlined
                    :options="presetOptions"
                    emit-value
                    map-options
                    :label="t('capture.preset')"
                    :disable="upload?.status === 'failed'"
                    class="q-mb-xl"
                />
                <section
                    v-if="preset === 'advanced'"
                    class="q-mb-xl"
                    :aria-label="t('capture.advancedSettings')"
                >
                    <reconstruction-settings v-model="advancedSettings" />
                    <p v-if="!hasValidSettings" class="text-negative q-mt-md" role="alert">
                        {{ t('capture.invalidSettings') }}
                    </p>
                </section>
            </section>

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
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import PageHeader from 'src/components/PageHeader.vue';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import UploadTransferProgress from 'src/components/UploadTransferProgress.vue';
import { ApiError } from 'src/lib/api';
import type { BuildingSelection } from 'src/lib/buildings';
import {
    type ReconstructionPreset,
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
} from 'src/lib/reconstruction-settings';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { useUploadQuery } from 'src/queries/uploads';
import { useCaptureDraftsStore } from 'src/stores/captureDrafts';

const props = defineProps<{ draftId: string }>();
const { t, locale } = useI18n();
const route = useRoute();
const store = useCaptureDraftsStore();
const draft = computed(() => store.drafts.get(props.draftId));
const uploadId = computed(() =>
    draft.value && 'uploadId' in draft.value ? draft.value.uploadId : '',
);
const video = computed(() =>
    draft.value && 'video' in draft.value ? draft.value.video : undefined,
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

function defaultBuildingSelection(): BuildingSelection {
    const buildingId = route.query.buildingId;
    if (typeof buildingId === 'string') return { buildingId };

    return {
        buildingId: null,
        building: {
            name: t('buildings.defaultName', { number: 1 }),
            latitude: null,
            longitude: null,
        },
    };
}

const buildingSelection = ref<BuildingSelection>(defaultBuildingSelection());
watch(
    () => route.query.buildingId,
    () => {
        buildingSelection.value = defaultBuildingSelection();
    },
);
const preset = ref<ReconstructionPreset>('indoors');
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const advancedSettings = ref(makeDefaultReconstructionSettings('advanced'));
const hasValidSettings = computed(() => isValidReconstructionSettings(advancedSettings.value));
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
