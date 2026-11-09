import { useMutation } from '@pinia/colada';
import { useI18n } from 'vue-i18n';
import { getAuthSubject } from 'src/lib/auth';
import { CaptureDraftService, type CaptureDraftSource } from 'src/lib/captureDraftService';

interface CreateCaptureDraftVariables {
    source: CaptureDraftSource;
    buildingId: string | null;
}

export function useCreateCaptureDraftMutation() {
    const { t } = useI18n();
    const ownerId = getAuthSubject();
    const service = new CaptureDraftService();

    return useMutation<string, CreateCaptureDraftVariables, unknown>({
        // The mutation variables may contain an entire video.
        gcTime: 0,
        mutation: ({ source, buildingId }) => {
            if (!ownerId || getAuthSubject() !== ownerId) {
                throw new Error('Capture drafts require the original signed-in account.');
            }
            return service.create({
                ownerId,
                source,
                buildingSelection:
                    buildingId === null
                        ? {
                              buildingId: null,
                              building: {
                                  name: t('buildings.defaultName', { number: 1 }),
                                  latitude: null,
                                  longitude: null,
                              },
                          }
                        : { buildingId },
            });
        },
    });
}
