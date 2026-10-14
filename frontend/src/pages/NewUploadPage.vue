<template>
    <q-page class="new-upload-page">
        <page-header :title="t('uploads.new.title')" />

        <section class="upload-form" :aria-label="t('uploads.new.title')">
            <p class="text-grey-7 q-ma-none">{{ t('uploads.new.instructions') }}</p>
            <file-picker-button v-model="file" accept="video/*" :disable="uploading || uploaded" />

            <div v-if="file" class="selected-file">
                <p class="text-weight-medium q-ma-none">{{ file.name }}</p>
                <p class="text-caption text-grey-7 q-ma-none">
                    {{ formatFileSize(file.size, locale) }}
                </p>
            </div>
            <p v-if="file?.size === 0" class="text-negative q-ma-none" role="alert">
                {{ t('uploads.new.emptyFile') }}
            </p>
            <q-banner v-if="errorMessage" class="bg-red-1 text-negative" role="alert">
                {{ errorMessage }}
            </q-banner>
            <q-banner v-if="uploaded" class="bg-green-1 text-positive" role="status">
                {{ t('uploads.new.completed', { filename: file?.name }) }}
                <template #action>
                    <q-btn
                        flat
                        no-caps
                        :label="t('uploads.new.viewUploads')"
                        @click="openUploads"
                    />
                </template>
            </q-banner>

            <upload-transfer-progress
                v-if="transferState.phase === 'uploading'"
                :progress="transferState.progress"
                :resumed="transferState.resumed"
            />
            <q-btn
                color="primary"
                unelevated
                no-caps
                :label="t(error ? 'common.retry' : 'uploads.new.start')"
                :loading="uploading"
                :disable="!canUpload"
                @click="startUpload"
            />
        </section>
    </q-page>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';
import FilePickerButton from 'src/components/FilePickerButton.vue';
import UploadTransferProgress from 'src/components/UploadTransferProgress.vue';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { formatFileSize } from 'src/lib/utils/formatFileSize';
import { useUploadVideoMutation } from 'src/mutations/uploads';

const { t, locale } = useI18n();
const router = useRouter();
const route = useRoute();
const $q = useQuasar();
const subject = getAuthSubject();
const file = shallowRef<File | null>(null);
const navigationError = ref('');
const {
    mutateAsync,
    isLoading: uploading,
    data,
    error,
    reset,
    transferState,
} = useUploadVideoMutation();
const uploaded = computed(() => data.value !== undefined);
const canUpload = computed(() => !!file.value?.size && !uploading.value && !uploaded.value);
const errorMessage = computed(() => {
    if (navigationError.value) return navigationError.value;
    if (!error.value) return '';
    if (error.value instanceof ApiError && [401, 403].includes(error.value.status)) {
        return t('uploads.new.authFailed');
    }
    if (error.value instanceof ApiError && error.value.status === 400) {
        return t('uploads.new.invalidVideo');
    }
    return t('uploads.new.failed');
});

let pageMounted = true;
onUnmounted(() => {
    // The independent transfer and its completion handler outlive this page.
    pageMounted = false;
});
watch(file, () => {
    reset();
    navigationError.value = '';
});

async function openUploads(): Promise<void> {
    try {
        const failure = await router.replace({ name: 'uploads' });
        if (failure && pageMounted) navigationError.value = t('uploads.new.navigationFailed');
    } catch {
        if (pageMounted) navigationError.value = t('uploads.new.navigationFailed');
    }
}

async function startUpload(): Promise<void> {
    if (!canUpload.value || !file.value) return;
    const selectedFile = file.value;
    try {
        await mutateAsync({ file: selectedFile });
    } catch {
        if (getAuthSubject() === subject && !pageMounted) {
            $q.notify({
                type: 'negative',
                message: t('uploads.new.backgroundFailed', {
                    filename: selectedFile.name,
                }),
            });
        }
        return;
    }
    if (getAuthSubject() !== subject) return;
    const onOriginalPage = pageMounted && route.name === 'new-upload';
    $q.notify({
        type: 'positive',
        message: t('uploads.new.completed', { filename: selectedFile.name }),
        ...(onOriginalPage
            ? {}
            : {
                  actions: [
                      {
                          label: t('uploads.new.viewUploads'),
                          handler: () => {
                              if (getAuthSubject() === subject) void openUploads();
                          },
                      },
                  ],
              }),
    });
    if (onOriginalPage) await openUploads();
}
</script>

<style scoped>
.new-upload-page {
    padding: 80px 16px 48px;
    background: white;
}

.upload-form {
    display: grid;
    gap: 1rem;
    max-width: 640px;
    margin-inline: auto;
}

.selected-file {
    overflow-wrap: anywhere;
}
</style>
