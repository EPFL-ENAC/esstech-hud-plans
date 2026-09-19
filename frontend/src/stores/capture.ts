import { defineStore } from 'pinia';
import { computed, shallowRef } from 'vue';
import { i18n } from 'src/i18n/instance';
import type { CapturedVideo } from 'src/lib/captured-video';
import type { BuildingSelection } from 'src/lib/buildings';
import {
    makeDefaultReconstructionSettings,
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
} from 'src/lib/reconstruction-settings';

export interface CaptureFormDraft {
    returnTo: string;
    videoFile: File | null;
    capturedVideo: CapturedVideo | null;
    buildingSelection: BuildingSelection;
    preset: ReconstructionPreset;
    advancedSettings: ReconstructionSettingsConfig;
}

export function makeEmptyCaptureDraft(returnTo: string = '/capture'): CaptureFormDraft {
    return {
        returnTo,
        videoFile: null,
        capturedVideo: null,
        buildingSelection: {
            buildingId: null,
            building: {
                name: i18n.global.t('buildings.defaultName', { number: 1 }),
                latitude: null,
                longitude: null,
            },
        },
        preset: 'indoors',
        advancedSettings: makeDefaultReconstructionSettings('advanced'),
    };
}

/** A single-use, memory-only handoff between recording and the capture form. */
export const useCaptureStore = defineStore('capture', () => {
    const draft = shallowRef<CaptureFormDraft | null>(null);
    const returnTo = computed(() => draft.value?.returnTo ?? null);

    function ensureDraft(): CaptureFormDraft {
        return (draft.value ??= makeEmptyCaptureDraft());
    }

    function setDraftVideo(video: CapturedVideo): void {
        draft.value = {
            ...ensureDraft(),
            videoFile: video.file,
            capturedVideo: video,
        };
    }

    function saveDraft(value: CaptureFormDraft): void {
        // Copy editable form data while retaining File identity for duration fallback.
        const { buildingSelection, advancedSettings } = value;
        draft.value = {
            ...value,
            buildingSelection:
                buildingSelection.buildingId === null
                    ? { buildingId: null, building: { ...buildingSelection.building } }
                    : { ...buildingSelection },
            advancedSettings: {
                ffmpeg: { ...advancedSettings.ffmpeg },
                framePicker: { ...advancedSettings.framePicker },
                colmap: { ...advancedSettings.colmap },
                brush: { ...advancedSettings.brush },
            },
        };
    }

    function clearDraft(): void {
        draft.value = null;
    }

    function takeDraft(): CaptureFormDraft | null {
        const saved = draft.value;
        clearDraft();
        return saved;
    }

    return {
        draft,
        ensureDraft,
        setDraftVideo,
        returnTo,
        saveDraft,
        takeDraft,
        clearDraft,
    };
});
