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
                    ? t('plans.splat.downloading', {
                          loaded: formatMb(loaded),
                          total: formatMb(total),
                      })
                    : t('plans.splat.downloadingUnknown', { loaded: formatMb(loaded) })
            }}
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { formatMb } from 'src/lib/utils/fetchProgress';
import { useSplatDownloadStore } from 'src/stores/splatDownload';

const { t } = useI18n();
const splatDownload = useSplatDownloadStore();
const progress = computed(() => splatDownload.progress ?? { loaded: 0, total: 0 });
const loaded = computed(() => progress.value.loaded);
const total = computed(() => progress.value.total);
const ratio = computed(() => (total.value > 0 ? Math.min(loaded.value / total.value, 1) : 0));
</script>
