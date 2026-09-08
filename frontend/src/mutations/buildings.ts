import { useI18n } from 'vue-i18n';
import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { ApiError, updateBuilding, type Building, type BuildingCreate } from 'src/lib/buildings';

export interface UpdateBuildingVariables {
    buildingId: string;
    details: BuildingCreate;
}

export function useUpdateBuildingMutation() {
    const { t } = useI18n();
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
            if (error.status === 404) return t('buildings.errors.unavailable');
            if (error.status === 401) return t('buildings.errors.sessionExpired');
            if (error.status === 422) return t('buildings.errors.invalidDetails');
            return t('buildings.errors.saveFailed');
        }
        return t('errors.connection');
    });

    return { ...mutation, errorMessage };
}
