import { defineStore } from 'pinia';
import { shallowReactive } from 'vue';

export type CaptureDraftSource = { uploadId: string } | { video: Blob };

export const useCaptureDraftsStore = defineStore('captureDrafts', () => {
    const drafts = shallowReactive(new Map<string, CaptureDraftSource>());

    function createDraft(source: CaptureDraftSource): string {
        const draftId = crypto.randomUUID();
        drafts.set(draftId, source);
        return draftId;
    }

    return { drafts, createDraft };
});
