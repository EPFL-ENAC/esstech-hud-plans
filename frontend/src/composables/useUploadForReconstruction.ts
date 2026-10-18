import { computed, onBeforeUnmount, readonly, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useQuasar } from 'quasar';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { useUploadVideoMutation } from 'src/mutations/uploads';

export function useUploadForReconstruction() {
    const router = useRouter();
    const { t } = useI18n();
    const $q = useQuasar();
    const subject = getAuthSubject();
    const { mutateAsync } = useUploadVideoMutation();
    const starting = ref(false);
    const navigating = ref(false);
    const uploadId = ref<string | null>(null);
    const errorMessage = ref('');
    const busy = computed(() => starting.value || navigating.value);
    let retainedFile: File | null = null;
    let transferActive = false;
    let mounted = true;

    onBeforeUnmount(() => {
        // The transfer and its notification handler continue after navigation.
        mounted = false;
    });

    function sameAccount(): boolean {
        return subject !== null && getAuthSubject() === subject;
    }

    async function openReconstruction(): Promise<void> {
        if (!mounted || !sameAccount() || !uploadId.value || navigating.value) return;
        navigating.value = true;
        errorMessage.value = '';
        try {
            const failure = await router.replace({
                name: 'reconstruction-from-upload',
                params: { uploadId: uploadId.value },
            });
            if (failure && mounted) {
                errorMessage.value = t('reconstructions.fromUpload.navigationFailed');
            }
        } catch {
            if (mounted) errorMessage.value = t('reconstructions.fromUpload.navigationFailed');
        } finally {
            navigating.value = false;
        }
    }

    function onUploadAvailable(id: string): void {
        if (uploadId.value !== null) return;
        uploadId.value = id;
        starting.value = false;
        void openReconstruction();
    }

    function uploadError(error: unknown): string {
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
            return t('uploads.new.authFailed');
        }
        if (error instanceof ApiError && error.status === 400) {
            return t('uploads.new.invalidVideo');
        }
        return t('uploads.new.failed');
    }

    async function transfer(file: File): Promise<void> {
        try {
            await mutateAsync({ file, onUploadAvailable });
        } catch (error) {
            if (!sameAccount()) return;
            if (mounted && uploadId.value === null) {
                errorMessage.value = uploadError(error);
            } else {
                $q.notify({
                    type: 'negative',
                    message: t('uploads.record.failed', { filename: file.name }),
                });
            }
            return;
        } finally {
            starting.value = false;
            transferActive = false;
        }
        if (sameAccount()) {
            $q.notify({
                type: 'positive',
                message: t('uploads.new.completed', { filename: file.name }),
            });
        }
    }

    function startUpload(file: File): void {
        if (!mounted || busy.value || transferActive || uploadId.value !== null) return;
        retainedFile = file;
        errorMessage.value = '';
        if (!sameAccount()) {
            errorMessage.value = t('uploads.new.authFailed');
            return;
        }
        if (file.size <= 0) {
            errorMessage.value = t('uploads.new.emptyFile');
            return;
        }
        starting.value = true;
        transferActive = true;
        void transfer(file);
    }

    async function retry(): Promise<void> {
        if (uploadId.value !== null) await openReconstruction();
        else if (retainedFile) startUpload(retainedFile);
    }

    return {
        startUpload,
        retry,
        busy,
        uploadId: readonly(uploadId),
        errorMessage: readonly(errorMessage),
    };
}
