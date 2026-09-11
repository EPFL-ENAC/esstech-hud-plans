import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { useVideoUploadStore } from 'src/stores/videoUpload';
import {
    type BuildingSelection,
    type Reconstruction,
    type ReconstructionSubmission,
    createBuildingFromReconstruction,
    createReconstruction,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';

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
            if (variables.buildingId === null) {
                const result = await createBuildingFromReconstruction(
                    variables.building,
                    variables,
                    videoUpload.update,
                );
                return result.reconstruction;
            }
            return createReconstruction(variables.buildingId, variables, videoUpload.update);
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
