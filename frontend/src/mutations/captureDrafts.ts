import { useMutation } from '@pinia/colada';
import { onScopeDispose } from 'vue';
import { useI18n } from 'vue-i18n';
import { getAuthSubject } from 'src/lib/auth';
import { CaptureDraftService, type CaptureDraftUploadChange } from 'src/lib/captureDraftService';
import { useUploadVideoMutation } from './uploads';

export type CreateCaptureDraftSource = { uploadId: string } | { video: File };

interface CreateCaptureDraftVariables {
    source: CreateCaptureDraftSource;
    buildingId: string | null;
}

export function useCreateCaptureDraftMutation({
    onCreate,
}: { onCreate?: (draftId: string) => void } = {}) {
    const { t } = useI18n();
    const ownerId = getAuthSubject();
    const service = new CaptureDraftService();
    const { mutateAsync: uploadVideo } = useUploadVideoMutation();
    let disposed = false;

    onScopeDispose(() => {
        disposed = true;
    });

    async function uploadDraftVideo(ownerId: string, draftId: string, file: File): Promise<void> {
        const update = (change: CaptureDraftUploadChange) =>
            service.updateUpload(draftId, { ownerId, change });
        let attachment = Promise.resolve();

        try {
            await update({ phase: 'uploading' });
            const { uploadId } = await uploadVideo({
                file,
                onUploadAvailable(uploadId) {
                    attachment = attachment
                        .then(() => update({ phase: 'uploading', uploadId }))
                        .catch((error: unknown) => {
                            console.warn('Could not attach upload to draft', error);
                        });
                },
            });
            await attachment;
            await update({ phase: 'uploaded', uploadId });
        } catch {
            await attachment;
            await update({ phase: 'failed' }).catch((error: unknown) => {
                console.warn('Could not save draft upload failure', error);
            });
        }
    }

    return useMutation<string, CreateCaptureDraftVariables, unknown>({
        // The mutation variables may contain an entire video.
        gcTime: 0,
        mutation: async ({ source, buildingId }) => {
            if (!ownerId || getAuthSubject() !== ownerId) {
                throw new Error('Capture drafts require the original signed-in account.');
            }
            const draftId = await service.create({
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
            if ('video' in source) void uploadDraftVideo(ownerId, draftId, source.video);
            return draftId;
        },
        onSuccess(draftId) {
            if (!disposed && getAuthSubject() === ownerId) onCreate?.(draftId);
        },
    });
}
