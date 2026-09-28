import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { useVideoUploadStore } from 'src/stores/videoUpload';
import {
    type BuildingSelection,
    type Reconstruction,
    type ReconstructionSubmission,
    createBuildingFromReconstructionResumable,
    createReconstructionResumable,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';
import { uploadVideoResumable } from 'src/lib/utils/tusUpload';

export type SubmitReconstructionVariables = ReconstructionSubmission & BuildingSelection;

function retainedBuildingId(
    error: unknown,
    variables: SubmitReconstructionVariables | undefined,
): string | null {
    return (
        getFailedBuildingId(error) ??
        (getFailedReconstructionId(error) ? (variables?.buildingId ?? null) : null)
    );
}

export function useSubmitReconstructionMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const videoUpload = useVideoUploadStore();
    const mutation = useMutation<Reconstruction, SubmitReconstructionVariables, unknown>({
        mutation: async (variables) => {
            videoUpload.reset();
            // Step 1: resumable upload to the tusd sidecar, reporting true
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
            const buildingId = data?.building_id ?? retainedBuildingId(error, variables);
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
        },
    });

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

    return { ...mutation, destinationBuildingId, errorMessage };
}
