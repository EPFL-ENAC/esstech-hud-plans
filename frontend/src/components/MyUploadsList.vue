<template>
    <section :aria-label="t('uploads.title')" class="q-pt-md">
        <QueryStateSwitcher
            class="uploads-query"
            :state="state"
            :async-status="isLoading ? 'loading' : 'idle'"
            :retry="refetch"
            :loading-message="t('uploads.loading')"
            :error-message="data ? t('uploads.refreshFailed') : t('uploads.loadFailed')"
        >
            <template #pending>
                <q-list separator class="uploads-list">
                    <q-item v-for="index in 3" :key="index" aria-hidden="true">
                        <q-item-section avatar>
                            <q-skeleton type="QAvatar" />
                        </q-item-section>
                        <q-item-section>
                            <q-skeleton type="text" width="60%" />
                            <q-skeleton type="text" width="40%" />
                        </q-item-section>
                    </q-item>
                </q-list>
            </template>
            <template #refreshing>
                <div class="q-px-md text-grey-7">
                    <q-spinner color="primary" class="q-mr-sm" />
                    {{ t('uploads.refreshing') }}
                </div>
            </template>
            <template #success>
                <q-list v-if="uploads.length" separator class="uploads-list" role="list">
                    <q-item v-for="upload in uploads" :key="upload.id" role="listitem">
                        <q-item-section avatar top>
                            <q-icon name="movie" color="primary" size="32px" aria-hidden="true" />
                        </q-item-section>
                        <q-item-section>
                            <q-item-label class="upload-text text-subtitle1 text-weight-medium">
                                {{ upload.filename }}
                            </q-item-label>
                            <q-item-label
                                v-if="upload.name.trim() && upload.name !== 'TODO'"
                                class="upload-text"
                            >
                                {{ upload.name }}
                            </q-item-label>
                            <q-item-label v-if="upload.description.trim()" class="upload-text">
                                {{ upload.description }}
                            </q-item-label>
                            <q-item-label caption class="upload-metadata">
                                <span>{{ formatFileSize(upload.size_bytes, locale) }}</span>
                                <span>{{
                                    t('uploads.created', {
                                        date: formatDate(upload.created_at),
                                    })
                                }}</span>
                                <span v-if="upload.uploaded_at">
                                    {{
                                        t('uploads.uploaded', {
                                            date: formatDate(upload.uploaded_at),
                                        })
                                    }}
                                </span>
                            </q-item-label>
                        </q-item-section>
                        <q-item-section side top>
                            <q-chip
                                dense
                                outline
                                :color="statusColors[upload.status]"
                                class="q-ma-none"
                            >
                                {{ uploadStatusLabel(upload) }}
                            </q-chip>
                            <div v-if="$slots.action" class="q-mt-sm">
                                <slot name="action" :upload="upload" />
                            </div>
                        </q-item-section>
                    </q-item>
                </q-list>
                <p v-else class="q-px-md text-grey-7" role="status">
                    {{ offset > 0 ? t('uploads.emptyPage') : t('uploads.empty') }}
                </p>
            </template>
        </QueryStateSwitcher>

        <nav
            v-if="(data && data.length > 0) || offset > 0"
            :aria-label="t('uploads.pagination')"
            class="row justify-center q-pa-md"
        >
            <q-pagination
                v-model="page"
                :max="page + Number(hasNext)"
                :max-pages="5"
                :boundary-numbers="false"
                :ellipses="false"
                direction-links
                color="primary"
                :disable="isLoading"
            />
        </nav>
    </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import type { UploadStatus, UserUpload } from 'src/lib/uploads';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { MY_UPLOADS_PAGE_SIZE, useMyUploadsQuery } from 'src/queries/uploads';

defineSlots<{
    action?(props: { upload: UserUpload }): unknown;
}>();

const { t, locale } = useI18n();
const offset = ref(0);
const { data, state, isLoading: queryIsLoading, refetch: refetchQuery } = useMyUploadsQuery(offset);
const manualRefreshing = ref(false);
const isLoading = computed(
    () => queryIsLoading.value && (data.value === undefined || manualRefreshing.value),
);
const uploads = computed(() => data.value?.slice(0, MY_UPLOADS_PAGE_SIZE) ?? []);
const hasNext = computed(() => (data.value?.length ?? 0) > MY_UPLOADS_PAGE_SIZE);
const page = computed({
    get: () => offset.value / MY_UPLOADS_PAGE_SIZE + 1,
    set: (value: number) => {
        offset.value = (value - 1) * MY_UPLOADS_PAGE_SIZE;
    },
});
const statusColors: Record<UploadStatus, string> = {
    pending: 'grey-7',
    uploaded: 'positive',
    failed: 'negative',
};
const percentFormatter = computed(
    () =>
        new Intl.NumberFormat(locale.value, {
            style: 'percent',
            maximumFractionDigits: 0,
        }),
);
const dateFormatter = computed(
    () =>
        new Intl.DateTimeFormat(locale.value, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        }),
);

function formatDate(value: string): string {
    return dateFormatter.value.format(new Date(value));
}

function uploadStatusLabel(upload: UserUpload): string {
    if (upload.status !== 'pending') {
        return t(`uploads.status.${upload.status}`);
    }

    const ratio =
        upload.size_bytes > 0
            ? Math.min(1, Math.max(0, upload.uploaded_bytes / upload.size_bytes))
            : 0;
    return percentFormatter.value.format(ratio);
}

async function refetch() {
    manualRefreshing.value = true;
    try {
        return await refetchQuery();
    } finally {
        manualRefreshing.value = false;
    }
}

defineExpose({ refetch, isLoading });
</script>

<style scoped>
.uploads-query :deep(.query-error) {
    margin-inline: 1rem;
}

.uploads-list {
    border-top: 1px solid rgba(0, 0, 0, 0.12);
    border-bottom: 1px solid rgba(0, 0, 0, 0.12);
}

.uploads-list .q-item {
    padding-block: 1rem;
}

.upload-text {
    overflow-wrap: anywhere;
}

.upload-metadata {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 1rem;
}
</style>
