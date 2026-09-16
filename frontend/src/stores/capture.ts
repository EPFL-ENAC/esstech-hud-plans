import { defineStore } from 'pinia';
import { computed, shallowRef } from 'vue';
import type { CapturedVideo } from 'src/lib/captured-video';
import type { BuildingSelection } from 'src/lib/buildings';
import type {
    ReconstructionPreset,
    ReconstructionSettingsConfig,
} from 'src/lib/reconstruction-settings';

export interface CaptureFormDraft {
    returnTo: string;
    videoFile: File | null;
    capturedVideo: CapturedVideo | null;
    buildingSelection: BuildingSelection;
    preset: ReconstructionPreset;
    advancedSettings: ReconstructionSettingsConfig;
}

/** A single-use, memory-only handoff between recording and the capture form. */
export const useCaptureStore = defineStore('capture', () => {
    const video = shallowRef<CapturedVideo | null>(null);
    const draft = shallowRef<CaptureFormDraft | null>(null);
    const returnTo = computed(() => draft.value?.returnTo ?? null);

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

    function setVideo(value: CapturedVideo): void {
        video.value = value;
    }

    function clearVideo(): void {
        video.value = null;
    }

    function takeVideo(): CapturedVideo | null {
        const captured = video.value;
        clearVideo();
        return captured;
    }

    return {
        video,
        draft,
        setVideo,
        takeVideo,
        clearVideo,
        returnTo,
        saveDraft,
        takeDraft,
        clearDraft,
    };
});
