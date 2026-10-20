<template>
    <q-dialog v-model="open" aria-labelledby="uploaded-video-picker-title">
        <q-card class="uploaded-video-picker">
            <q-card-section>
                <h2 id="uploaded-video-picker-title" class="text-h6 q-ma-none">
                    {{ t('uploads.picker.title') }}
                </h2>
            </q-card-section>

            <q-card-section class="picker-content">
                <query-state-switcher
                    :state="state"
                    :async-status="asyncStatus"
                    :retry="refetch"
                    :loading-message="t('uploads.loading')"
                    :error-message="t('uploads.loadFailed')"
                >
                    <template #success>
                        <q-list v-if="uploads.length" separator>
                            <q-item
                                v-for="upload in uploads"
                                :key="upload.id"
                                clickable
                                v-ripple
                                class="picker-upload"
                                @click="selectedId = upload.id"
                            >
                                <q-item-section side>
                                    <q-radio
                                        v-model="selectedId"
                                        :val="upload.id"
                                        :aria-label="upload.filename"
                                    />
                                </q-item-section>
                                <q-item-section>
                                    <q-item-label class="upload-text">
                                        {{ upload.filename }}
                                    </q-item-label>
                                    <q-item-label
                                        v-if="upload.name.trim() && upload.name !== 'TODO'"
                                        class="upload-text"
                                    >
                                        {{ upload.name }}
                                    </q-item-label>
                                    <q-item-label caption>
                                        {{ formatFileSize(upload.size_bytes, locale) }}
                                        ·
                                        {{ formatDate(upload.uploaded_at ?? upload.created_at) }}
                                    </q-item-label>
                                </q-item-section>
                            </q-item>
                        </q-list>
                        <p v-else class="text-grey-7" role="status">
                            {{ t(offset ? 'uploads.emptyPage' : 'uploads.picker.empty') }}
                        </p>
                    </template>
                </query-state-switcher>

                <nav v-if="offset > 0 || hasNext" :aria-label="t('uploads.pagination')">
                    <q-pagination
                        v-model="page"
                        :max="page + (hasNext ? 1 : 0)"
                        :max-pages="5"
                        :disable="asyncStatus === 'loading'"
                    />
                </nav>
            </q-card-section>

            <q-card-actions align="right">
                <q-btn v-close-popup flat no-caps :label="t('common.cancel')" />
                <q-btn
                    color="primary"
                    no-caps
                    :label="t('uploads.picker.useVideo')"
                    :disable="!selectedUpload || asyncStatus === 'loading'"
                    @click="confirm"
                />
            </q-card-actions>
        </q-card>
    </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import type { UserUpload } from 'src/lib/uploads';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { MY_UPLOADS_PAGE_SIZE, useUploadedVideosQuery } from 'src/queries/uploads';

const open = defineModel<boolean>({ required: true });
const emit = defineEmits<{ select: [upload: UserUpload] }>();
const { t, locale } = useI18n();
const offset = ref(0);
const selectedId = ref<string | null>(null);
const { data, state, asyncStatus, refetch } = useUploadedVideosQuery(offset, open);
const uploads = computed(() => data.value?.slice(0, MY_UPLOADS_PAGE_SIZE) ?? []);
const hasNext = computed(() => (data.value?.length ?? 0) > MY_UPLOADS_PAGE_SIZE);
const selectedUpload = computed(() =>
    uploads.value.find((upload) => upload.id === selectedId.value),
);
const page = computed({
    get: () => offset.value / MY_UPLOADS_PAGE_SIZE + 1,
    set: (value: number) => {
        selectedId.value = null;
        offset.value = (value - 1) * MY_UPLOADS_PAGE_SIZE;
    },
});

watch(open, (value) => {
    if (value) {
        offset.value = 0;
        selectedId.value = null;
    }
});

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(value));
}

function confirm(): void {
    if (!selectedUpload.value || asyncStatus.value === 'loading') return;
    emit('select', selectedUpload.value);
    open.value = false;
}
</script>

<style scoped>
.uploaded-video-picker {
    display: flex;
    flex-direction: column;
    width: 600px;
    max-width: calc(100vw - 32px);
    max-height: 85dvh;
}

.picker-content {
    overflow-y: auto;
    min-height: 0;
}

.upload-text {
    overflow-wrap: anywhere;
}
</style>
