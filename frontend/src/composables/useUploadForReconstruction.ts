import { computed, onBeforeUnmount, readonly, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { useScheduleVideoUploadMutation } from 'src/mutations/uploads';

export function useUploadForReconstruction() {
    const router = useRouter();
    const route = useRoute();
    const { t } = useI18n();
    const subject = getAuthSubject();
    const { mutateAsync: scheduleUpload } = useScheduleVideoUploadMutation();
    const scheduling = ref(false);
    const navigating = ref(false);
    const localUploadId = ref<string | null>(null);
    const errorMessage = ref('');
    const busy = computed(() => scheduling.value || navigating.value);
    let retainedFile: File | null = null;
    let mounted = true;

    onBeforeUnmount(() => {
        mounted = false;
    });

    function sameAccount(): boolean {
        return subject !== null && getAuthSubject() === subject;
    }

    async function openReconstruction(): Promise<void> {
        const id = localUploadId.value;
        if (!mounted || !sameAccount() || id === null || navigating.value) return;

        navigating.value = true;
        errorMessage.value = '';
        try {
            const failure = await router.replace({
                name: 'reconstruction-from-local-upload',
                params: { localUploadId: id },
                query: { buildingId: route.query.buildingId },
            });
            if (failure && mounted && sameAccount()) {
                errorMessage.value = t('reconstructions.fromUpload.navigationFailed');
            }
        } catch {
            if (mounted && sameAccount()) {
                errorMessage.value = t('reconstructions.fromUpload.navigationFailed');
            }
        } finally {
            navigating.value = false;
        }
    }

    async function startUpload(file: File): Promise<void> {
        if (!mounted || busy.value || localUploadId.value !== null) return;

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

        scheduling.value = true;
        try {
            const upload = await scheduleUpload({ file });
            if (!mounted || !sameAccount()) return;

            localUploadId.value = upload.localUploadId;
            retainedFile = null;
            await openReconstruction();
        } catch (error) {
            if (mounted && sameAccount()) {
                const authFailed = error instanceof ApiError && [401, 403].includes(error.status);
                errorMessage.value = t(
                    authFailed
                        ? 'uploads.new.authFailed'
                        : 'reconstructions.fromUpload.scheduleFailed',
                );
            }
        } finally {
            scheduling.value = false;
        }
    }

    async function retry(): Promise<void> {
        if (localUploadId.value !== null) {
            await openReconstruction();
        } else if (retainedFile) {
            await startUpload(retainedFile);
        }
    }

    return {
        startUpload,
        retry,
        busy,
        localUploadId: readonly(localUploadId),
        errorMessage: readonly(errorMessage),
    };
}
