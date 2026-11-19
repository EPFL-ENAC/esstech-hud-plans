import { ApiError } from 'src/lib/api';
import { idempotentRequestFailureAction } from 'src/lib/idempotentRequests';
import {
    LocalUploadStorageError,
    type LocalUploadsRegistry,
    type RemoteUpload,
} from 'src/lib/localUploadsRegistry';
import {
    NetworkDependentTask,
    type FailureAction,
    type TaskOptions,
    type TaskSnapshot,
} from 'src/lib/networkDependentTasks';
import { uploadVideoTus } from 'src/lib/utils/taskTusUpload';

export interface VideoUploadResult {
    uploadId: string;
    resumed: boolean;
}

export interface VideoUploadTaskOptions extends TaskOptions<VideoUploadResult> {
    localUploadId: string;
    uploads: LocalUploadsRegistry;
    onUploadAvailable?(this: void, uploadId: string): void | Promise<void>;
}

export interface VideoUploadData {
    localUploadId: string;
}

export class VideoUploadTask extends NetworkDependentTask<VideoUploadResult> {
    readonly localUploadId: string;

    private readonly uploads: LocalUploadsRegistry;
    private readonly onUploadAvailable: VideoUploadTaskOptions['onUploadAvailable'];

    // Retain a failed metadata write so retry can save the same remote location.
    private pendingRemote: RemoteUpload | null = null;
    private notifiedUploadId: string | null = null;

    constructor({ localUploadId, uploads, onUploadAvailable, ...options }: VideoUploadTaskOptions) {
        super(options);

        if (typeof localUploadId !== 'string' || localUploadId.length === 0) {
            throw new Error('Upload task has no local upload ID.');
        }

        this.localUploadId = localUploadId;
        this.uploads = uploads;
        this.onUploadAvailable = onUploadAvailable;
    }

    serialize(): TaskSnapshot<VideoUploadData> {
        return {
            ...this.serializeBase(),
            type: 'video-upload',
            data: {
                localUploadId: this.localUploadId,
            },
        };
    }

    static deserialize(
        snapshot: TaskSnapshot<VideoUploadData>,
        uploads: LocalUploadsRegistry,
    ): VideoUploadTask {
        const task = new VideoUploadTask({
            id: snapshot.id,
            createdAt: snapshot.createdAt,
            ownerId: snapshot.ownerId,
            label: snapshot.label,
            localUploadId: snapshot.data?.localUploadId,
            uploads,
        });

        task.restoreState(snapshot.state);
        return task;
    }

    protected override async resume(signal: AbortSignal): Promise<VideoUploadResult> {
        signal.throwIfAborted();

        await this.savePendingRemote();
        signal.throwIfAborted();

        const record = await this.uploads.get(this.ownerId, this.localUploadId);
        signal.throwIfAborted();

        const file = await this.uploads.getFile(this.ownerId, this.localUploadId);
        signal.throwIfAborted();

        this.setProgress({
            completed: this.state.progress?.completed ?? 0,
            total: file.size,
        });

        const result = await uploadVideoTus(file, {
            ownerId: this.ownerId,
            uploadUrl: record.remote?.uploadUrl ?? null,
            signal,
            onCheckpoint: async (remote) => {
                this.pendingRemote = remote;
                await this.savePendingRemote();
            },
            onProgress: ({ loaded, total }) => {
                if (signal.aborted) return;

                this.setProgress({
                    completed: loaded,
                    total: total > 0 ? total : file.size,
                });
            },
            onUploadAvailable: ({ uploadId }) => {
                if (signal.aborted || this.notifiedUploadId === uploadId) return;

                this.notifiedUploadId = uploadId;
                void this.notifyUploadAvailable(uploadId);
            },
        });

        signal.throwIfAborted();

        this.setProgress({
            completed: file.size,
            total: file.size,
        });

        return {
            uploadId: result.uploadId,
            resumed: result.resumed,
        };
    }

    protected override failureAction(error: unknown): FailureAction {
        if (error instanceof LocalUploadStorageError) {
            return 'blocked';
        }

        if (error instanceof ApiError && [0, 409, 423].includes(error.status)) {
            return 'retry';
        }

        return idempotentRequestFailureAction(error);
    }

    private async savePendingRemote(): Promise<void> {
        if (this.pendingRemote === null) return;

        await this.uploads.setRemote(this.ownerId, this.localUploadId, this.pendingRemote);

        this.pendingRemote = null;
    }

    private async notifyUploadAvailable(uploadId: string): Promise<void> {
        try {
            await this.onUploadAvailable?.(uploadId);
        } catch (error) {
            console.warn('Upload availability callback failed', error);
        }
    }
}
