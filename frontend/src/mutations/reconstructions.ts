import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { i18n } from 'src/i18n/instance';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { TaskPersistenceError } from 'src/lib/networkDependentTasks';
import type { Page } from 'src/lib/pagination';
import {
    ReconstructionSubmissionTask,
    type ReconstructionSubmission,
    type ReconstructionSubmissionResult,
} from 'src/lib/reconstructionSubmissionTask';
import { useNetworkDependentTasks, type TaskSubmission } from 'src/stores/networkDependentTasks';
import {
    type Reconstruction,
    cancelReconstruction,
    isReconstructionProcessing,
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

export type SubmitReconstructionVariables = ReconstructionSubmission;

function invalidateSubmissionQueries(
    queryCache: ReturnType<typeof useQueryCache>,
    ownerId: string,
    buildingId: string | null,
): void {
    void Promise.all([
        queryCache.invalidateQueries({ key: ['buildings', ownerId, 'picker'] }),
        queryCache.invalidateQueries({ key: ['buildings', ownerId, 'list'] }),
        queryCache.invalidateQueries({ key: ['buildings', ownerId, 'locations'] }),
        ...(buildingId === null
            ? []
            : [
                  queryCache.invalidateQueries({
                      key: ['buildings', ownerId, 'detail', buildingId],
                      exact: true,
                  }),
                  queryCache.invalidateQueries({
                      key: ['buildings', ownerId, 'detail', buildingId, 'reconstructions', 'list'],
                  }),
              ]),
    ]).catch((error: unknown) => console.warn('Could not refresh building data', error));
}

export function useSubmitReconstructionMutation() {
    const queue = useNetworkDependentTasks();
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const mutation = useMutation<
        TaskSubmission<ReconstructionSubmissionResult>,
        SubmitReconstructionVariables,
        unknown
    >({
        mutation: (submission) => {
            if (subject === null || getAuthSubject() !== subject) {
                throw new ApiError('Submission account has changed', 401, null);
            }
            return queue.submit(
                new ReconstructionSubmissionTask({
                    ownerId: subject,
                    label: i18n.global.t('capture.submittingReconstruction'),
                    submission,
                    onCompleted: ({ buildingId }) => {
                        invalidateSubmissionQueries(queryCache, subject, buildingId);
                    },
                }),
            );
        },
    });

    const destinationBuildingId = computed(() => {
        const outcome = mutation.data.value;
        if (!outcome) return null;
        return outcome.status === 'completed'
            ? outcome.result.buildingId
            : (mutation.variables.value?.buildingId ?? null);
    });
    const errorMessage = computed(() =>
        mutation.error.value === null ||
        (mutation.error.value instanceof DOMException && mutation.error.value.name === 'AbortError')
            ? ''
            : mutation.error.value instanceof TaskPersistenceError
              ? mutation.error.value.message
              : getReconstructionSubmissionErrorMessage(mutation.error.value),
    );

    return {
        ...mutation,
        destinationBuildingId,
        errorMessage,
    };
}
