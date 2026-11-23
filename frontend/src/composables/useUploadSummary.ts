import type { AsyncStatus, DataState } from '@pinia/colada';
import {
    computed,
    onScopeDispose,
    ref,
    shallowRef,
    toValue,
    watch,
    type MaybeRefOrGetter,
} from 'vue';
import { useAuthentication } from 'src/composables/useAuthentication';
import { LocalUploadsRegistry, type LocalUploadRecord } from 'src/lib/localUploadsRegistry';
import type { TaskStatus } from 'src/lib/networkDependentTasks';
import type { UploadReference, UploadStatus, UserUpload } from 'src/lib/uploads';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { VideoUploadTask } from 'src/lib/videoUploadTask';
import { useUploadQuery } from 'src/queries/uploads';
import { useNetworkDependentTasks } from 'src/stores/networkDependentTasks';

export interface UploadSummaryData {
    filename: string;
    sizeBytes: number;
    status:
        | { source: 'device' }
        | { source: 'task'; value: TaskStatus }
        | { source: 'server'; value: UploadStatus };
    progress: FetchProgress | null;
}

function summarizeLocal(record: LocalUploadRecord, task?: VideoUploadTask): UploadSummaryData {
    const progress = task?.state.status === 'running' ? task.state.progress : null;
    return {
        filename: record.file.name,
        sizeBytes: record.file.size,
        status: task ? { source: 'task', value: task.state.status } : { source: 'device' },
        progress: progress
            ? { loaded: progress.completed, total: progress.total ?? record.file.size }
            : null,
    };
}

function summarizeRemote(upload: UserUpload): UploadSummaryData {
    return {
        filename: upload.filename,
        sizeBytes: upload.size_bytes,
        status: { source: 'server', value: upload.status },
        progress:
            upload.status === 'pending'
                ? { loaded: upload.uploaded_bytes, total: upload.size_bytes }
                : null,
    };
}

export function useUploadSummary(reference: MaybeRefOrGetter<UploadReference>) {
    const { ownerId, isAuthenticated } = useAuthentication();
    const initialOwnerId = ownerId.value;
    const activeOwnerId = computed(() =>
        ownerId.value === initialOwnerId && isAuthenticated.value ? initialOwnerId : null,
    );
    const uploads = new LocalUploadsRegistry();
    const queue = useNetworkDependentTasks();
    const localUploadId = computed(() => toValue(reference).localUploadId);
    const localRecord = shallowRef<LocalUploadRecord>();
    const localError = shallowRef<Error | null>(null);
    const readingLocal = ref(false);
    let localRead: AbortController | undefined;

    async function loadLocalUpload(): Promise<void> {
        localRead?.abort();
        localRead = undefined;
        localRecord.value = undefined;
        localError.value = null;
        readingLocal.value = false;

        const id = localUploadId.value;
        const owner = activeOwnerId.value;
        if (!id || owner === null) return;

        localRead = new AbortController();
        const { signal } = localRead;
        readingLocal.value = true;
        try {
            const record = await uploads.get(owner, id);
            signal.throwIfAborted();
            localRecord.value = record;
            readingLocal.value = false;

            if (record.remote === null) {
                const remote = await uploads.waitForRemote(owner, id, signal);
                signal.throwIfAborted();
                localRecord.value = { ...record, remote };
            }
        } catch (error) {
            if (signal.aborted) return;
            localError.value =
                error instanceof Error
                    ? error
                    : new Error('Could not read local upload', {
                          cause: error,
                      });
            readingLocal.value = false;
        }
    }

    onScopeDispose(() => localRead?.abort());
    watch([localUploadId, activeOwnerId], loadLocalUpload, { immediate: true, flush: 'sync' });

    const remoteUploadId = computed(() => {
        if (activeOwnerId.value === null) return '';
        return toValue(reference).uploadId ?? localRecord.value?.remote?.uploadId ?? '';
    });
    const remoteQuery = useUploadQuery(remoteUploadId);

    const localSummary = computed(() => {
        const record = localRecord.value;
        if (!record) return undefined;

        const task = queue.tasks.find(
            (task): task is VideoUploadTask =>
                task instanceof VideoUploadTask &&
                task.ownerId === record.ownerId &&
                task.localUploadId === record.id,
        );
        return summarizeLocal(record, task);
    });

    const state = computed<DataState<UploadSummaryData, Error>>(() => {
        if (activeOwnerId.value === null) {
            return {
                status: 'error',
                data: undefined,
                error: new Error('Upload account unavailable'),
            };
        }

        const remote = remoteUploadId.value ? remoteQuery.state.value : undefined;
        const data = remote?.data ? summarizeRemote(remote.data) : localSummary.value;
        const error = localError.value ?? remote?.error;

        if (error) return { status: 'error', data, error };
        if (data) return { status: 'success', data, error: null };
        return { status: 'pending', data: undefined, error: null };
    });

    const asyncStatus = computed<AsyncStatus>(() => {
        const readingRemote =
            remoteUploadId.value !== '' && remoteQuery.asyncStatus.value === 'loading';
        return readingLocal.value || readingRemote ? 'loading' : 'idle';
    });

    function refetch(): void {
        if (remoteUploadId.value) {
            void remoteQuery.refetch();
        } else if (localUploadId.value && activeOwnerId.value !== null) {
            void loadLocalUpload();
        }
    }

    return { state, asyncStatus, refetch };
}
