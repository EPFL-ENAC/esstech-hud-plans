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
            <template v-if="stateLabel !== ''"> · {{ stateLabel }}</template>
        </div>
        <div v-if="canPause || canResume || canCancel" class="row q-gutter-xs q-mt-xs">
            <q-btn
                v-if="canPause"
                flat
                dense
                size="sm"
                :label="t('transfers.pause')"
                @click="splatDownload.pause()"
            />
            <q-btn
                v-if="canResume"
                flat
                dense
                size="sm"
                :label="t('transfers.resume')"
                @click="splatDownload.resume()"
            />
            <q-btn
                v-if="canCancel"
                flat
                dense
                size="sm"
                color="negative"
                :label="t('transfers.cancel')"
                @click="splatDownload.cancel()"
            />
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
const stateLabel = computed(() =>
    splatDownload.state === 'idle' ? '' : t(`transfers.download.${splatDownload.state}`),
);
const canPause = computed(() => splatDownload.state === 'downloading');
const canResume = computed(() => splatDownload.state === 'paused');
const canCancel = computed(() =>
    (['downloading', 'paused'] as string[]).includes(splatDownload.state),
);
</script>
