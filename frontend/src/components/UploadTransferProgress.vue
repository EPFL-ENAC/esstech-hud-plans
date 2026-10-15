<template>
    <div role="status" aria-live="polite">
        <q-linear-progress
            :value="ratio"
            :indeterminate="!progress?.total"
            rounded
            color="primary"
        />
        <p class="text-caption text-grey-7 q-mt-sm q-mb-none">
            {{ caption }}
        </p>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { formatFileSize } from 'src/lib/utils/formatFileSize';

const props = defineProps<{ progress: FetchProgress | null; resumed: boolean }>();
const { t, locale } = useI18n();
const ratio = computed(() =>
    props.progress?.total ? Math.min(props.progress.loaded / props.progress.total, 1) : 0,
);
const caption = computed(() => {
    if (!props.progress?.total) {
        return t(props.resumed ? 'uploads.new.resuming' : 'uploads.new.starting');
    }
    return t(props.resumed ? 'uploads.new.resumedProgress' : 'uploads.new.progress', {
        loaded: formatFileSize(props.progress.loaded, locale.value),
        total: formatFileSize(props.progress.total, locale.value),
    });
});
</script>
