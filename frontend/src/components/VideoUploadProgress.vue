<template>
    <div v-if="state.phase !== 'idle'" role="status">
        <q-linear-progress
            :value="ratio"
            :indeterminate="total === 0"
            rounded
            color="primary"
            :animation-speed="150"
        />
        <div class="text-caption text-grey-7 q-mt-xs">
            {{ caption }}
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { formatMb } from 'src/lib/utils/fetchProgress';
import type { ReconstructionSubmissionState } from 'src/mutations/reconstructions';

const { t } = useI18n();
const props = defineProps<{ state: ReconstructionSubmissionState }>();
const progress = computed(() =>
    props.state.phase === 'uploading' && props.state.progress
        ? props.state.progress
        : { loaded: 0, total: 0 },
);
const loaded = computed(() => progress.value.loaded);
const total = computed(() => progress.value.total);
const ratio = computed(() => (total.value > 0 ? Math.min(loaded.value / total.value, 1) : 0));
const caption = computed(() => {
    if (props.state.phase === 'idle') return '';
    if (props.state.phase === 'submitting') return t('capture.submittingReconstruction');
    if (props.state.resumed) return t('capture.resumingUpload');
    return total.value > 0
        ? t('capture.uploading', {
              loaded: formatMb(loaded.value),
              total: formatMb(total.value),
          })
        : t('capture.uploadingUnknown', { loaded: formatMb(loaded.value) });
});
</script>
