<template>
    <q-page class="reconstruction-from-upload-page">
        <page-header :title="t('reconstructions.new')">
            <q-btn
                flat
                no-caps
                color="primary"
                icon="refresh"
                :label="t('uploads.refresh')"
                :disable="isLoading"
                @click="refetch()"
            />
        </page-header>

        <query-state-switcher
            :state="state"
            :async-status="asyncStatus"
            :retry="refetch"
            :loading-message="t('uploads.loading')"
            :error-message="loadError"
        >
            <template #success="{ data: upload }">
                <q-card flat bordered class="upload-summary q-mb-xl">
                    <q-card-section>
                        <div class="text-weight-medium">{{ upload.filename }}</div>
                        <div class="text-caption text-grey-7">
                            {{ formatFileSize(upload.size_bytes, locale) }}
                            · {{ t(`uploads.status.${upload.status}`) }}
                        </div>
                    </q-card-section>
                </q-card>
                <p v-if="upload.status === 'failed'" class="text-negative" role="alert">
                    {{ t('reconstructions.fromUpload.failedUpload') }}
                </p>
                <reconstruction-form
                    :key="upload.id"
                    v-model:building-selection="buildingSelection"
                    v-model:preset="preset"
                    v-model:advanced-settings="advancedSettings"
                    :source="{ uploadId: upload.id }"
                    :disabled="!canSubmitUpload"
                />
            </template>
        </query-state-switcher>
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref, toRef } from 'vue';
import { useI18n } from 'vue-i18n';
import PageHeader from 'src/components/PageHeader.vue';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import ReconstructionForm from 'src/components/ReconstructionForm.vue';
import { ApiError } from 'src/lib/api';
import type { BuildingSelection } from 'src/lib/buildings';
import {
    type ReconstructionPreset,
    makeDefaultReconstructionSettings,
} from 'src/lib/reconstruction-settings';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { useUploadQuery } from 'src/queries/uploads';

const props = defineProps<{ uploadId: string }>();
const { t, locale } = useI18n();
const { data, state, asyncStatus, isLoading, refetch } = useUploadQuery(toRef(props, 'uploadId'));
const loadError = computed(() => {
    const error = state.value.error;
    return error instanceof ApiError && [404, 422].includes(error.status)
        ? t('reconstructions.fromUpload.unavailable')
        : t('reconstructions.fromUpload.loadFailed');
});
const canSubmitUpload = computed(
    () =>
        state.value.status === 'success' &&
        !isLoading.value &&
        (data.value?.status === 'pending' || data.value?.status === 'uploaded'),
);
const buildingSelection = ref<BuildingSelection>({
    buildingId: null,
    building: { name: t('buildings.defaultName', { number: 1 }), latitude: null, longitude: null },
});
const preset = ref<ReconstructionPreset>('indoors');
const advancedSettings = ref(makeDefaultReconstructionSettings('advanced'));
</script>

<style scoped>
.reconstruction-from-upload-page {
    padding: 64px 16px 48px;
    background: #fff;
    color: var(--q-dark);
}

.upload-summary {
    overflow-wrap: anywhere;
}
</style>
