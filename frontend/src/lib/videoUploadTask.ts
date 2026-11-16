import { reactive, readonly } from 'vue';
import { ApiError } from 'src/lib/api';
import { idempotentRequestFailureAction } from 'src/lib/idempotentRequests';
import {
    NetworkDependentTask,
    type FailureAction,
    type TaskOptions,
} from 'src/lib/networkDependentTasks';
import { uploadVideoTus } from 'src/lib/utils/taskTusUpload';

export interface VideoUploadResult {
    uploadId: string;
    resumed: boolean;
}

export interface VideoUploadTaskOptions extends TaskOptions<VideoUploadResult> {
    file: File;
    onUploadAvailable?(this: void, uploadId: string): void | Promise<void>;
}

export interface VideoUploadState {
    uploadId: string | null;
    resumed: boolean;
}

export class VideoUploadTask extends NetworkDependentTask<VideoUploadResult> {
    readonly file: File;

    private uploadUrl: string | null = null;

    private readonly mutableUploadState = reactive<VideoUploadState>({
        uploadId: null,
        resumed: false,
    });

    readonly uploadState = readonly(this.mutableUploadState);

    private readonly onUploadAvailable: VideoUploadTaskOptions['onUploadAvailable'];

    constructor({ file, onUploadAvailable, ...options }: VideoUploadTaskOptions) {
        super(options);

        if (file.size <= 0) {
            throw new ApiError('Upload file is empty', 400, null);
        }

        this.file = file;
        this.onUploadAvailable = onUploadAvailable;
        this.mutableState.progress = {
            completed: 0,
            total: file.size,
        };
    }

    protected override async resume(signal: AbortSignal): Promise<VideoUploadResult> {
        signal.throwIfAborted();

        this.mutableUploadState.resumed ||= this.uploadUrl !== null;

        const result = await uploadVideoTus(this.file, {
            ownerId: this.ownerId,
            uploadUrl: this.uploadUrl,
            signal,
            onProgress: ({ loaded, total }) => {
                if (signal.aborted) return;

                this.mutableState.progress = {
                    completed: loaded,
                    total: total > 0 ? total : this.file.size,
                };
            },
            onUploadAvailable: (upload) => {
                if (signal.aborted) return;

                this.uploadUrl = upload.uploadUrl;
                this.mutableUploadState.resumed ||= upload.resumed;

                if (this.mutableUploadState.uploadId === upload.uploadId) {
                    return;
                }

                this.mutableUploadState.uploadId = upload.uploadId;
                void this.notifyUploadAvailable(upload.uploadId);
            },
        });

        signal.throwIfAborted();

        this.mutableUploadState.uploadId = result.uploadId;
        this.mutableUploadState.resumed ||= result.resumed;
        this.mutableState.progress = {
            completed: this.file.size,
            total: this.file.size,
        };

        return {
            uploadId: result.uploadId,
            resumed: this.mutableUploadState.resumed,
        };
    }

    protected override failureAction(error: unknown): FailureAction {
        if (error instanceof ApiError && [0, 409, 423].includes(error.status)) {
            return 'retry';
        }

        return idempotentRequestFailureAction(error);
    }

    private async notifyUploadAvailable(uploadId: string): Promise<void> {
        try {
            await this.onUploadAvailable?.(uploadId);
        } catch (error) {
            console.warn('Upload availability callback failed', error);
        }
    }
}
