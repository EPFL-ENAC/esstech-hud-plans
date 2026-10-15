import { useMutation, useQueryCache } from '@pinia/colada';
import { readonly, shallowRef } from 'vue';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { uploadVideoResumable, type ResumableUploadResult } from 'src/lib/utils/tusUpload';

export interface UploadVideoVariables {
    file: File;
}

export type UploadTransferState =
    | { phase: 'idle' }
    | { phase: 'uploading'; progress: FetchProgress | null; resumed: boolean };

export function useUploadVideoMutation() {
    const subject = getAuthSubject();
    const queryCache = useQueryCache();
    const transferState = shallowRef<UploadTransferState>({ phase: 'idle' });

    function invalidateUploads(): void {
        if (subject === null) return;
        void queryCache
            .invalidateQueries({
                key: ['uploads', subject, 'list'],
            })
            .catch((error: unknown) => console.warn('Could not refresh upload data', error));
    }

    const mutation = useMutation<ResumableUploadResult, UploadVideoVariables, unknown>({
        mutation: async ({ file }) => {
            if (subject === null || getAuthSubject() !== subject) {
                throw new ApiError('Upload account has changed', 401, null);
            }
            if (file.size <= 0) throw new ApiError('Upload file is empty', 400, null);
            transferState.value = { phase: 'uploading', progress: null, resumed: false };
            try {
                return await uploadVideoResumable(file, {
                    subject,
                    onProgress(progress) {
                        if (transferState.value.phase !== 'uploading') return;
                        transferState.value = { ...transferState.value, progress };
                    },
                    onResumed() {
                        if (transferState.value.phase !== 'uploading') return;
                        transferState.value = { ...transferState.value, resumed: true };
                    },
                    onUploadAvailable: invalidateUploads,
                });
            } finally {
                transferState.value = { phase: 'idle' };
            }
        },
        onSettled: invalidateUploads,
    });

    return { ...mutation, transferState: readonly(transferState) };
}
