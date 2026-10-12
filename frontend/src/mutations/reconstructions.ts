import { useMutation, useQueryCache } from '@pinia/colada';
import { computed, readonly, shallowRef } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
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

export type ReconstructionSubmissionState =
    | { phase: 'idle' }
    | { phase: 'uploading'; progress: FetchProgress | null; resumed: boolean }
    | { phase: 'submitting' };

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
    const submissionState = shallowRef<ReconstructionSubmissionState>({ phase: 'idle' });
    const mutation = useMutation<Reconstruction, SubmitReconstructionVariables, unknown>({
        mutation: async (variables) => {
            submissionState.value = { phase: 'uploading', progress: null, resumed: false };
            try {
                const { uploadId } = await uploadVideoResumable(variables.video, {
                    onProgress(progress) {
                        if (submissionState.value.phase !== 'uploading') return;
                        submissionState.value = { ...submissionState.value, progress };
                    },
                    onResumed() {
                        if (submissionState.value.phase !== 'uploading') return;
                        submissionState.value = { ...submissionState.value, resumed: true };
                    },
                });
                submissionState.value = { phase: 'submitting' };
                if (variables.buildingId === null) {
                    const result = await createBuildingFromReconstructionResumable(
                        variables.building,
                        uploadId,
                        variables.settings,
                    );
                    return result.reconstruction;
                }
                return await createReconstructionResumable(
                    variables.buildingId,
                    uploadId,
                    variables.settings,
                );
            } finally {
                submissionState.value = { phase: 'idle' };
            }
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

    return {
        ...mutation,
        submissionState: readonly(submissionState),
        destinationBuildingId,
        errorMessage,
    };
}
