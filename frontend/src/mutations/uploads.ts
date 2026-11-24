import { useMutation, useQueryCache } from '@pinia/colada';
import { readonly, shallowRef } from 'vue';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { LocalUploadsRegistry } from 'src/lib/localUploadsRegistry';
import { VideoUploadTask } from 'src/lib/videoUploadTask';
import { useNetworkDependentTasks } from 'src/stores/networkDependentTasks';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { uploadVideoResumable, type ResumableUploadResult } from 'src/lib/utils/tusUpload';

export interface UploadVideoVariables {
    file: File;
    onUploadAvailable?: (uploadId: string) => void;
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
                key: ['uploads', subject],
            })
            .catch((error: unknown) => console.warn('Could not refresh upload data', error));
    }

    const mutation = useMutation<ResumableUploadResult, UploadVideoVariables, unknown>({
        mutation: async ({ file, onUploadAvailable }) => {
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
                    onUploadAvailable(uploadId) {
                        invalidateUploads();
                        onUploadAvailable?.(uploadId);
                    },
                });
            } finally {
                transferState.value = { phase: 'idle' };
            }
        },
        onSettled: invalidateUploads,
    });

    return { ...mutation, transferState: readonly(transferState) };
}

export interface ScheduleVideoUploadVariables {
    file: File;
    onUploadAvailable?: (uploadId: string) => void | Promise<void>;
}

export interface ScheduledVideoUpload {
    localUploadId: string;
    taskId: string;
}

export function useScheduleVideoUploadMutation() {
    const subject = getAuthSubject();
    const uploads = new LocalUploadsRegistry();
    const queue = useNetworkDependentTasks();
    const queryCache = useQueryCache();

    function requireOwner(): string {
        if (subject === null || getAuthSubject() !== subject) {
            throw new ApiError('Upload account has changed', 401, null);
        }

        return subject;
    }

    function invalidateUploads(): void {
        if (subject === null) return;

        void queryCache
            .invalidateQueries({
                key: ['uploads', subject],
            })
            .catch((error: unknown) => console.warn('Could not refresh upload data', error));
    }

    return useMutation<ScheduledVideoUpload, ScheduleVideoUploadVariables, unknown>({
        mutation: async ({ file, onUploadAvailable }) => {
            const ownerId = requireOwner();
            const upload = await uploads.create(ownerId, file);

            requireOwner();

            const task = new VideoUploadTask({
                ownerId,
                label: file.name,
                localUploadId: upload.id,
                uploads,
                onUploadAvailable: async (uploadId) => {
                    invalidateUploads();
                    await onUploadAvailable?.(uploadId);
                },
                onCompleted: invalidateUploads,
            });

            await queue.submit(task, { waitForFirstTry: false });

            return {
                localUploadId: upload.id,
                taskId: task.id,
            };
        },
    });
}
