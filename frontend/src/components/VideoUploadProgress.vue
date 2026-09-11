<template>
    <div role="status">
        <q-linear-progress
            :value="ratio"
            :indeterminate="total === 0"
            rounded
            color="primary"
            :animation-speed="150"
        />
        <div class="text-caption text-grey-7 q-mt-xs">
            {{
                total > 0
                    ? t('capture.uploading', {
                          loaded: formatMb(loaded),
                          total: formatMb(total),
                      })
                    : t('capture.uploadingUnknown', { loaded: formatMb(loaded) })
            }}
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { formatMb } from 'src/lib/utils/fetchProgress';
import { useVideoUploadStore } from 'src/stores/videoUpload';

const { t } = useI18n();
const videoUpload = useVideoUploadStore();
const progress = computed(() => videoUpload.progress ?? { loaded: 0, total: 0 });
const loaded = computed(() => progress.value.loaded);
const total = computed(() => progress.value.total);
const ratio = computed(() => (total.value > 0 ? Math.min(loaded.value / total.value, 1) : 0));
</script>
