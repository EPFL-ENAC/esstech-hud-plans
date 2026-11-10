import { onScopeDispose, readonly, ref, shallowReadonly } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import { getAuthSubject } from 'src/lib/auth';
import {
    CaptureDraftService,
    type CaptureDraft,
    type CaptureDraftForm,
    type CaptureDraftSourceInfo,
} from 'src/lib/captureDraftService';
import { useDebouncedAutosave } from './useDebouncedAutosave';

export function useCaptureDraft(draftId: string) {
    const ownerId = getAuthSubject();
    const service = new CaptureDraftService();
    const draft = ref<CaptureDraft | null>(null);
    const loadStatus = ref<'loading' | 'ready' | 'missing' | 'error'>('loading');
    let disposed = false;
    let sourceDuringRead: CaptureDraftSourceInfo | undefined;

    const unsubscribe = ownerId
        ? service.listenForUploadChanges(draftId, { ownerId }, (source) => {
              if (getAuthSubject() !== ownerId) return;
              if (draft.value) applySource(draft.value, source);
              else sourceDuringRead = source;
          })
        : undefined;

    onScopeDispose(() => {
        disposed = true;
        unsubscribe?.();
    });

    async function retryLoad(): Promise<void> {
        loadStatus.value = 'loading';
        sourceDuringRead = undefined;

        try {
            const record = ownerId ? await service.get(draftId, { ownerId }) : null;
            if (disposed) return;

            const loaded = ownerId === getAuthSubject() ? record : null;
            if (loaded && sourceDuringRead) applySource(loaded, sourceDuringRead);
            sourceDuringRead = undefined;
            draft.value = loaded;
            loadStatus.value = loaded ? 'ready' : 'missing';
        } catch {
            if (!disposed) loadStatus.value = 'error';
        }
    }

    const {
        status: saveStatus,
        flush,
        retry: retrySave,
    } = useDebouncedAutosave(
        () => (loadStatus.value === 'ready' ? draft.value?.form : undefined),
        async (form) => {
            if (!ownerId || ownerId !== getAuthSubject()) {
                throw new Error('The capture draft account has changed.');
            }
            await service.updateForm(draftId, { ownerId, form: snapshotForm(form) });
        },
        300,
    );
    onBeforeRouteLeave(flush);
    onBeforeRouteUpdate(flush);
    void retryLoad();

    return {
        draft: shallowReadonly(draft),
        loadStatus: readonly(loadStatus),
        saveStatus,
        retryLoad,
        retrySave,
    };
}

function applySource(draft: CaptureDraft, source: CaptureDraftSourceInfo): void {
    if ('uploadId' in source) {
        draft.source = source;
    } else if ('video' in draft.source) {
        const { video } = draft.source;
        draft.source = source.phase ? { video, phase: source.phase } : { video };
    }
}

function snapshotForm(form: CaptureDraftForm): CaptureDraftForm {
    const { buildingSelection, preset, advancedSettings } = form;
    const { ffmpeg, framePicker, colmap, brush } = advancedSettings;
    return {
        buildingSelection:
            buildingSelection.buildingId === null
                ? { buildingId: null, building: { ...buildingSelection.building } }
                : { buildingId: buildingSelection.buildingId },
        preset,
        advancedSettings: {
            ffmpeg: { ...ffmpeg },
            framePicker: { ...framePicker },
            colmap: { ...colmap },
            brush: { ...brush },
        },
    };
}
