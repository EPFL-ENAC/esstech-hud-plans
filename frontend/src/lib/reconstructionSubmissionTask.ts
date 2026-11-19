import { readonly, shallowRef } from 'vue';
import { ApiError } from 'src/lib/api';
import {
    type BuildingFromReconstruction,
    type BuildingSelection,
    type Reconstruction,
    type SplatGenerationSettings,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';
import { idempotentRequestFailureAction, requestIdempotentJson } from 'src/lib/idempotentRequests';
import { LocalUploadStorageError, type LocalUploadsRegistry } from 'src/lib/localUploadsRegistry';
import {
    NetworkDependentTask,
    type FailureAction,
    type TaskOptions,
    type TaskSnapshot,
} from 'src/lib/networkDependentTasks';

export type ReconstructionUploadReference =
    | { uploadId: string; localUploadId?: never }
    | { localUploadId: string; uploadId?: never };

export type ReconstructionSubmission = BuildingSelection &
    ReconstructionUploadReference & {
        settings: SplatGenerationSettings;
    };

export interface ReconstructionSubmissionTaskOptions extends TaskOptions<ReconstructionSubmissionResult> {
    submission: ReconstructionSubmission;
    uploads: LocalUploadsRegistry;
}

export interface ReconstructionSubmissionResult {
    buildingId: string | null;
    reconstructionId: string | null;
    reconstruction: Reconstruction | null;
    warning: string | null;
}

type SubmissionResponse = Reconstruction | BuildingFromReconstruction;

export interface ReconstructionSubmissionData {
    submission: ReconstructionSubmission;
}

export class ReconstructionSubmissionTask extends NetworkDependentTask<ReconstructionSubmissionResult> {
    private readonly submission: ReconstructionSubmission;
    private readonly uploads: LocalUploadsRegistry;
    private readonly buildingId: string | null;
    private readonly path: string;

    private readonly mutableResult = shallowRef<ReconstructionSubmissionResult | null>(null);

    readonly result = readonly(this.mutableResult);

    constructor({ submission, uploads, ...options }: ReconstructionSubmissionTaskOptions) {
        super(options);

        this.submission = JSON.parse(JSON.stringify(submission)) as ReconstructionSubmission;
        this.uploads = uploads;
        this.buildingId = this.submission.buildingId;
        this.path =
            this.buildingId === null
                ? '/buildings/from-reconstruction/from-upload'
                : `/buildings/${encodeURIComponent(this.buildingId)}/reconstructions/from-upload`;
    }

    serialize(): TaskSnapshot<ReconstructionSubmissionData> {
        return {
            ...this.serializeBase(),
            type: 'reconstruction-submission',
            data: {
                submission: JSON.parse(JSON.stringify(this.submission)) as ReconstructionSubmission,
            },
        };
    }

    static deserialize(
        snapshot: TaskSnapshot<ReconstructionSubmissionData>,
        uploads: LocalUploadsRegistry,
    ): ReconstructionSubmissionTask {
        const task = new ReconstructionSubmissionTask({
            id: snapshot.id,
            createdAt: snapshot.createdAt,
            ownerId: snapshot.ownerId,
            label: snapshot.label,
            submission: snapshot.data.submission,
            uploads,
        });
        task.restoreState(snapshot.state);
        return task;
    }

    private async resolveUploadId(signal: AbortSignal): Promise<string> {
        const submission = this.submission;
        if (submission.localUploadId === undefined) return submission.uploadId;

        const remote = await this.uploads.waitForRemote(
            this.ownerId,
            submission.localUploadId,
            signal,
        );
        return remote.uploadId;
    }

    protected override async resume(signal: AbortSignal): Promise<ReconstructionSubmissionResult> {
        signal.throwIfAborted();

        try {
            const uploadId = await this.resolveUploadId(signal);
            signal.throwIfAborted();

            const submission = this.submission;
            const body = JSON.stringify({
                upload_id: uploadId,
                settings: submission.settings,
                ...(submission.buildingId === null ? { building: submission.building } : {}),
            });

            const response = await requestIdempotentJson<SubmissionResponse>(this.path, {
                idempotencyKey: this.id,
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                signal,
            });

            signal.throwIfAborted();

            const reconstruction =
                response === null
                    ? null
                    : 'reconstruction' in response
                      ? response.reconstruction
                      : response;

            const result: ReconstructionSubmissionResult = {
                buildingId: reconstruction?.building_id ?? this.buildingId,
                reconstructionId: reconstruction?.id ?? null,
                reconstruction,
                warning: null,
            };
            this.mutableResult.value = result;
            return result;
        } catch (error: unknown) {
            signal.throwIfAborted();

            const buildingId = getFailedBuildingId(error);
            const reconstructionId = getFailedReconstructionId(error);

            // Retained IDs confirm acceptance despite a later failure.
            if (
                error instanceof ApiError &&
                error.status === 503 &&
                (buildingId !== null || reconstructionId !== null)
            ) {
                const result: ReconstructionSubmissionResult = {
                    buildingId: buildingId ?? this.buildingId,
                    reconstructionId,
                    reconstruction: null,
                    warning: getReconstructionSubmissionErrorMessage(error),
                };
                this.mutableResult.value = result;
                return result;
            }

            // Present domain messages while preserving classification.
            if (error instanceof ApiError) {
                throw new ApiError(
                    getReconstructionSubmissionErrorMessage(error),
                    error.status,
                    error.body,
                );
            }

            if (error instanceof TypeError) {
                throw new TypeError(getReconstructionSubmissionErrorMessage(error), {
                    cause: error,
                });
            }

            throw error;
        }
    }

    protected override failureAction(error: unknown): FailureAction {
        if (error instanceof LocalUploadStorageError) return 'blocked';

        return idempotentRequestFailureAction(error);
    }
}
