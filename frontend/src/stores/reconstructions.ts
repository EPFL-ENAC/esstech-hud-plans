import { defineStore } from 'pinia';
import { ref } from 'vue';

/**
 * Tracks reconstructions whose cancellation the local UI shows before the
 * backend confirms it. The ids are a frontend-only optimistic state; the
 * backend never returns a 'cancelling' status.
 */
export const useReconstructionProcessingStore = defineStore('reconstructionProcessing', () => {
    const cancellingIds = ref<Set<string>>(new Set());

    function markCancelling(id: string): void {
        cancellingIds.value.add(id);
    }

    function clearCancelling(id: string): void {
        cancellingIds.value.delete(id);
    }

    function isCancelling(id: string): boolean {
        return cancellingIds.value.has(id);
    }

    return { cancellingIds, markCancelling, clearCancelling, isCancelling };
});
