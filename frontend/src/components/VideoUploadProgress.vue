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
            <template v-if="stateLabel !== ''"> · {{ stateLabel }}</template>
            <template v-if="chunksLabel !== ''"> · {{ chunksLabel }}</template>
        </div>
        <div v-if="canPause || canResume || canCancel" class="row q-gutter-xs q-mt-xs">
            <q-btn
                v-if="canPause"
                flat
                dense
                size="sm"
                :label="t('transfers.pause')"
                @click="videoUpload.pause()"
            />
            <q-btn
                v-if="canResume"
                flat
                dense
                size="sm"
                :label="t('transfers.resume')"
                @click="videoUpload.resume()"
            />
            <q-btn
                v-if="canCancel"
                flat
                dense
                size="sm"
                color="negative"
                :label="t('transfers.cancel')"
                @click="videoUpload.cancel()"
            />
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
const stateLabel = computed(() =>
    videoUpload.state === 'idle' ? '' : t(`transfers.upload.${videoUpload.state}`),
);
const chunksLabel = computed(() =>
    videoUpload.chunks === null
        ? ''
        : t('transfers.uploadChunks', {
              received: videoUpload.chunks.received,
              total: videoUpload.chunks.total,
          }),
);
const canPause = computed(() =>
    (['creating', 'uploading'] as string[]).includes(videoUpload.state),
);
const canResume = computed(() => videoUpload.state === 'paused');
const canCancel = computed(() =>
    (['creating', 'uploading', 'paused'] as string[]).includes(videoUpload.state),
);
</script>
