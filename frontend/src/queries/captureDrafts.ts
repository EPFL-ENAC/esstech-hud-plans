export interface CaptureDraftUploadState {
    phase: 'uploading' | 'uploaded' | 'failed';
    uploadId: string | null;
}

export function captureDraftUploadKey(ownerId: string, draftId: string) {
    return ['capture-drafts', ownerId, draftId, 'upload'] as const;
}
