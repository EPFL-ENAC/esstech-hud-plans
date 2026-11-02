import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import type { Page } from 'src/lib/pagination';
import {
    type BuildingSelection,
    type Reconstruction,
    type SplatGenerationSettings,
    createBuildingFromReconstructionUpload,
    createReconstructionFromUpload,
    cancelReconstruction,
    isReconstructionProcessing,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';

export interface CancelReconstructionVariables {
    buildingId: string;
    reconstructionId: string;
}

export function useCancelReconstructionMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const listKey = (buildingId: string) =>
        ['buildings', subject, 'detail', buildingId, 'reconstructions', 'list'] as const;

    function updateCachedReconstruction(
        { buildingId, reconstructionId }: CancelReconstructionVariables,
        update: (reconstruction: Reconstruction) => Reconstruction,
    ) {
        const key = listKey(buildingId);
        queryCache.cancelQueries({ key });
        for (const entry of queryCache.getEntries({ key })) {
            const page = queryCache.getQueryData<Page<Reconstruction>>(entry.key);
            if (!page?.items.some(({ id }) => id === reconstructionId)) continue;
            queryCache.setQueryData<Page<Reconstruction>>(entry.key, {
                ...page,
                items: page.items.map((row) => (row.id === reconstructionId ? update(row) : row)),
            });
        }
    }

    return useMutation<
        Reconstruction,
        CancelReconstructionVariables,
        unknown,
        { previousReconstructions: Map<Reconstruction, Reconstruction> }
    >({
        onMutate(variables) {
            const previousReconstructions = new Map<Reconstruction, Reconstruction>();
            updateCachedReconstruction(variables, (row) => {
                if (row.status === 'cancelling' || !isReconstructionProcessing(row.status))
                    return row;
                const optimistic: Reconstruction = { ...row, status: 'cancelling' };
                previousReconstructions.set(optimistic, row);
                return optimistic;
            });
            return { previousReconstructions };
        },
        mutation: ({ buildingId, reconstructionId }) =>
            cancelReconstruction(buildingId, reconstructionId),
        onSuccess(reconstruction, variables) {
            updateCachedReconstruction(variables, (row) =>
                reconstruction.status === 'cancelling' && !isReconstructionProcessing(row.status)
                    ? row
                    : reconstruction,
            );
        },
        onError(_error, variables, { previousReconstructions }) {
            // A refetch confirming cancellation replaces the optimistic object.
            updateCachedReconstruction(
                variables,
                (row) => previousReconstructions?.get(row) ?? row,
            );
        },
        onSettled(_data, _error, { buildingId }) {
            void Promise.all([
                queryCache.invalidateQueries({ key: listKey(buildingId) }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'list'] }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'picker'] }),
            ]).catch((error: unknown) =>
                console.warn('Could not refresh reconstruction data', error),
            );
        },
    });
}

export type SubmitReconstructionVariables = BuildingSelection & {
    uploadId: string;
    settings: SplatGenerationSettings;
};

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
    const mutation = useMutation<Reconstruction, SubmitReconstructionVariables, unknown>({
        mutation: async (variables) => {
            if (variables.buildingId === null) {
                const result = await createBuildingFromReconstructionUpload(
                    variables.building,
                    variables.uploadId,
                    variables.settings,
                );
                return result.reconstruction;
            }
            return createReconstructionFromUpload(
                variables.buildingId,
                variables.uploadId,
                variables.settings,
            );
        },
        onSettled(data, error, variables) {
            const buildingId = data?.building_id ?? retainedBuildingId(error, variables);
            if (buildingId === null) return;

            // Mark cached data stale immediately, but don't let background refresh
            // failures change the outcome of a submission that already finished.
            void Promise.all([
                queryCache.invalidateQueries({ key: ['buildings', subject, 'picker'] }),
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
        destinationBuildingId,
        errorMessage,
    };
}
