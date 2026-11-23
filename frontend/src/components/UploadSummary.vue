<template>
    <query-state-switcher
        :state="state"
        :async-status="asyncStatus"
        :retry="refetch"
        :loading-message="t('uploads.loading')"
        :error-message="t('uploads.summary.loadFailed')"
    >
        <template #success="{ data: summary }">
            <q-card flat bordered class="upload-summary">
                <q-card-section>
                    <div class="text-weight-medium">{{ summary.filename }}</div>
                    <div class="text-caption text-grey-7">
                        {{ formatFileSize(summary.sizeBytes, locale) }}
                        · <span aria-live="polite">{{ statusLabel(summary.status) }}</span>
                    </div>
                    <upload-transfer-progress
                        v-if="summary.progress"
                        class="q-mt-md"
                        :progress="summary.progress"
                        :resumed="false"
                    />
                </q-card-section>
            </q-card>
        </template>
    </query-state-switcher>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import UploadTransferProgress from 'src/components/UploadTransferProgress.vue';
import { useUploadSummary, type UploadSummaryData } from 'src/composables/useUploadSummary';
import type { UploadReference } from 'src/lib/uploads';
import { formatFileSize } from 'src/lib/utils/formatFileSize';

const props = defineProps<{ uploadReference: UploadReference }>();
const { t, locale } = useI18n();
const { state, asyncStatus, refetch } = useUploadSummary(() => props.uploadReference);

function statusLabel(status: UploadSummaryData['status']): string {
    switch (status.source) {
        case 'device':
            return t('uploads.summary.savedOnDevice');
        case 'task':
            return t(`tasks.status.${status.value}`);
        case 'server':
            return t(`uploads.status.${status.value}`);
    }
}
</script>

<style scoped>
.upload-summary {
    overflow-wrap: anywhere;
}
</style>
