import { useMutation, useQueryCache } from '@pinia/colada';
import { useI18n } from 'vue-i18n';
import { getAuthSubject } from 'src/lib/auth';
import { CaptureDraftService } from 'src/lib/captureDraftService';
import { captureDraftUploadKey, type CaptureDraftUploadState } from 'src/queries/captureDrafts';
import { useUploadVideoMutation } from './uploads';

export type CreateCaptureDraftSource = { uploadId: string } | { video: File };

interface CreateCaptureDraftVariables {
    source: CreateCaptureDraftSource;
    buildingId: string | null;
}

export function useCreateCaptureDraftMutation() {
    const { t } = useI18n();
    const ownerId = getAuthSubject();
    const service = new CaptureDraftService();
    const queryCache = useQueryCache();
    const { mutateAsync: uploadVideo } = useUploadVideoMutation();

    async function uploadDraftVideo(ownerId: string, draftId: string, file: File): Promise<void> {
        const key = captureDraftUploadKey(ownerId, draftId);
        let attachedId: string | null = null;
        let lastReportedId: string | undefined;
        let attachment = Promise.resolve();

        function publish(phase: CaptureDraftUploadState['phase']): void {
            queryCache.setQueryData<CaptureDraftUploadState>(key, { phase, uploadId: attachedId });
        }

        async function attach(uploadId: string, completed = false): Promise<void> {
            await service.attachUpload(draftId, { ownerId, uploadId, completed });
            attachedId = uploadId;
            publish(completed ? 'uploaded' : 'uploading');
        }

        publish('uploading');
        try {
            const result = await uploadVideo({
                file,
                onUploadAvailable(uploadId) {
                    if (uploadId === lastReportedId) return;
                    lastReportedId = uploadId;
                    attachment = attachment
                        .then(() => attach(uploadId))
                        .catch(() => publish('failed'));
                },
            });
            await attachment;
            await attach(result.uploadId, true);
        } catch {
            await attachment;
            publish('failed');
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
    });
}
