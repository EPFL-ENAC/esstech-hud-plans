import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';

export const useSplatDownloadStore = defineStore('splatDownload', () => {
    const progress = ref<FetchProgress | null>(null);

    function update(value: FetchProgress): void {
        progress.value = value;
    }

    function reset(): void {
        progress.value = null;
    }

    return { progress, update, reset };
});
