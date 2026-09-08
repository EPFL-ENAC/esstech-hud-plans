import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { ApiError, updateBuilding, type Building, type BuildingCreate } from 'src/lib/buildings';

export interface UpdateBuildingVariables {
    buildingId: string;
    details: BuildingCreate;
}

export function useUpdateBuildingMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const mutation = useMutation<Building, UpdateBuildingVariables, unknown>({
        mutation: ({ buildingId, details }) => updateBuilding(buildingId, details),
        onSuccess(building) {
            const key = ['buildings', subject, 'detail', building.id];
            queryCache.cancelQueries({ key, exact: true });
            queryCache.setQueryData<Building>(key, building);

            // Refresh dependent views without making a successful save depend on them.
            void Promise.all([
                queryCache.invalidateQueries({ key: ['buildings', subject, 'all'] }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'list'] }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'locations'] }),
            ]).catch((error: unknown) => console.warn('Could not refresh building data', error));
        },
    });

    const errorMessage = computed(() => {
        const error = mutation.error.value;
        if (error === null) return '';
        if (error instanceof ApiError) {
            if (error.status === 404) return 'This building is no longer available.';
            if (error.status === 401) return 'Your session has expired. Sign in again to save.';
            if (error.status === 422) return 'Check the building details, then try again.';
            return 'Could not save the building. Please try again.';
        }
        return 'Could not reach the server. Check your connection and try again.';
    });

    return { ...mutation, errorMessage };
}
