import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';

/** Byte progress of the video upload shown while submitting a reconstruction. */
export const useVideoUploadStore = defineStore('videoUpload', () => {
    /** null while idle or before the first progress event arrives. */
    const progress = ref<FetchProgress | null>(null);

    function update(value: FetchProgress): void {
        progress.value = value;
    }

    function reset(): void {
        progress.value = null;
    }

    return { progress, update, reset };
});
