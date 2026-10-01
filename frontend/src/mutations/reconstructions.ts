import { useMutation, useQueryCache } from '@pinia/colada';
import { computed, type Ref } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { useVideoUploadStore } from 'src/stores/videoUpload';
import {
    type BuildingSelection,
    type Reconstruction,
    type ReconstructionSubmission,
    type SplatGenerationSettings,
    createBuildingFromReconstructionResumable,
    createReconstructionResumable,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';
import { uploadVideoResumable } from 'src/lib/utils/tusUpload';

export type SubmitReconstructionVariables = ReconstructionSubmission & BuildingSelection;

/** Variables for scheduling a reconstruction from an already finished tus upload. */
export type CreateReconstructionVariables = BuildingSelection & {
    uploadId: string;
    settings: SplatGenerationSettings;
};

type ReconstructionMutationVariables =
    | SubmitReconstructionVariables
    | CreateReconstructionVariables;

function retainedBuildingId(
    error: unknown,
    variables: ReconstructionMutationVariables | undefined,
): string | null {
    return (
        getFailedBuildingId(error) ??
        (getFailedReconstructionId(error) ? (variables?.buildingId ?? null) : null)
    );
}

function refreshBuildingData(
    queryCache: ReturnType<typeof useQueryCache>,
    subject: string | null,
    buildingId: string | null,
): void {
    if (buildingId === null) return;

    // Mark cached data stale immediately, but don't let background refresh
    // failures change the outcome of a submission that already finished.
    void Promise.all([
        queryCache.invalidateQueries({ key: ['buildings', subject, 'all'] }),
        queryCache.invalidateQueries({ key: ['buildings', subject, 'list'] }),
        queryCache.invalidateQueries({ key: ['buildings', subject, 'locations'] }),
        queryCache.invalidateQueries({
            key: ['buildings', subject, 'detail', buildingId],
            exact: true,
        }),
        queryCache.invalidateQueries({
            key: ['buildings', subject, 'detail', buildingId, 'reconstructions', 'list'],
        }),
    ]).catch((error: unknown) => console.warn('Could not refresh building data', error));
}

function useReconstructionMutationStatus(mutation: {
    data: Ref<Reconstruction | undefined>;
    error: Ref<unknown>;
    variables: Ref<ReconstructionMutationVariables | undefined>;
}) {
    const destinationBuildingId = computed(
        () =>
            mutation.data.value?.building_id ??
            retainedBuildingId(mutation.error.value, mutation.variables.value),
    );
    const errorMessage = computed(() =>
        mutation.error.value === null
            ? ''
            : getReconstructionSubmissionErrorMessage(mutation.error.value),
    );
    return { destinationBuildingId, errorMessage };
}

export function useSubmitReconstructionMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const videoUpload = useVideoUploadStore();
    const mutation = useMutation<Reconstruction, SubmitReconstructionVariables, unknown>({
        mutation: async (variables) => {
            videoUpload.reset();
            // Step 1: resumable upload through the API upload proxy (which
            // forwards to tusd), reporting true
            // network bytes. Step 2: submit the finished upload for scheduling;
            // the pipeline copies the video out of the tusd staging directory.
            const { uploadId } = await uploadVideoResumable(variables.video, {
                onProgress: videoUpload.update,
                onResumed: () => videoUpload.setResumed(true),
            });
            // The upload step is done; the caption must not claim a resumed
            // upload during the step-2 submission.
            videoUpload.setResumed(false);
            if (variables.buildingId === null) {
                const result = await createBuildingFromReconstructionResumable(
                    variables.building,
                    uploadId,
                    variables.settings,
                );
                return result.reconstruction;
            }
            return createReconstructionResumable(
                variables.buildingId,
                uploadId,
                variables.settings,
            );
        },
        onSettled(data, error, variables) {
            refreshBuildingData(
                queryCache,
                subject,
                data?.building_id ?? retainedBuildingId(error, variables),
            );
        },
    });

    return { ...mutation, ...useReconstructionMutationStatus(mutation) };
}

export function useCreateReconstructionMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const mutation = useMutation<Reconstruction, CreateReconstructionVariables, unknown>({
        mutation: async (variables) => {
            if (variables.buildingId === null) {
                const result = await createBuildingFromReconstructionResumable(
                    variables.building,
                    variables.uploadId,
                    variables.settings,
                );
                return result.reconstruction;
            }
            return createReconstructionResumable(
                variables.buildingId,
                variables.uploadId,
                variables.settings,
            );
        },
        onSettled(data, error, variables) {
            refreshBuildingData(
                queryCache,
                subject,
                data?.building_id ?? retainedBuildingId(error, variables),
            );
        },
    });

    return { ...mutation, ...useReconstructionMutationStatus(mutation) };
}
