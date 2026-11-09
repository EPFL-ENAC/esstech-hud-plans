import { readonly, ref, shallowReadonly } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import { getAuthSubject } from 'src/lib/auth';
import {
    CaptureDraftService,
    type CaptureDraft,
    type CaptureDraftForm,
} from 'src/lib/captureDraftService';
import { useDebouncedAutosave } from './useDebouncedAutosave';

export function useCaptureDraft(draftId: string) {
    const ownerId = getAuthSubject();
    const service = new CaptureDraftService();
    const draft = ref<CaptureDraft | null>(null);
    const loadStatus = ref<'loading' | 'ready' | 'missing' | 'error'>('loading');

    async function retryLoad(): Promise<void> {
        loadStatus.value = 'loading';
        try {
            const record = ownerId ? await service.get(draftId, { ownerId }) : null;
            draft.value = ownerId === getAuthSubject() ? record : null;
            loadStatus.value = draft.value ? 'ready' : 'missing';
        } catch {
            loadStatus.value = 'error';
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
