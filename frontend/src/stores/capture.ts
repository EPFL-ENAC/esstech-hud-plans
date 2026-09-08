import { defineStore } from 'pinia';
import { shallowRef } from 'vue';
import type { CapturedVideo } from 'src/lib/captured-video';

/** A single-use, memory-only handoff between recording and the capture form. */
export const useCaptureStore = defineStore('capture', () => {
    const video = shallowRef<CapturedVideo | null>(null);

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

    return { video, setVideo, takeVideo, clearVideo };
});
