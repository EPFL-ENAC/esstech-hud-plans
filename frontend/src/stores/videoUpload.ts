import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';
import { deleteUploadSession } from 'src/lib/uploads/chunkUpload';
import { deleteUploadSession as deleteStoredUploadSession } from 'src/lib/localTransfers';

/** States of the chunked video upload. The single-shot path stays idle. */
export type VideoUploadState =
    | 'idle'
    | 'creating'
    | 'uploading'
    | 'finalizing'
    | 'done'
    | 'failed'
    | 'paused';

/** State machine of the video upload shown while submitting a reconstruction. */
export const useVideoUploadStore = defineStore('videoUpload', () => {
    /** null while idle or before the first progress event arrives. */
    const progress = ref<FetchProgress | null>(null);
    const state = ref<VideoUploadState>('idle');
    const sessionId = ref<string | null>(null);
    const chunks = ref<{ received: number; total: number } | null>(null);
    const errorMessage = ref('');

    let controller: AbortController | null = null;

    /** Kept for the single-shot path: record raw upload byte progress only. */
    function update(value: FetchProgress): void {
        progress.value = value;
    }

    function reset(): void {
        progress.value = null;
        state.value = 'idle';
        sessionId.value = null;
        chunks.value = null;
        errorMessage.value = '';
        controller = null;
    }

    /** Start a chunked upload pass with its own abort controller. */
    function beginChunked(nextController: AbortController): void {
        reset();
        controller = nextController;
        state.value = 'creating';
    }

    /** Swap in a fresh controller after a paused pass was resumed. */
    function attach(nextController: AbortController): void {
        controller = nextController;
    }

    function setSession(id: string): void {
        sessionId.value = id;
    }

    function setState(next: VideoUploadState): void {
        state.value = next;
    }

    function setChunks(received: number, total: number): void {
        chunks.value = { received, total };
    }

    function fail(message: string): void {
        errorMessage.value = message;
        state.value = 'failed';
    }

    /** Abort in-flight chunk requests and wait for a resume. */
    function pause(): void {
        if (state.value !== 'creating' && state.value !== 'uploading') return;
        controller?.abort();
        state.value = 'paused';
    }

    /** Let the paused submit loop continue its pass. */
    function resume(): void {
        if (state.value !== 'paused') return;
        state.value = 'uploading';
    }

    /** Cancel the upload: abort requests and clean the server side. */
    async function cancel(): Promise<void> {
        const id = sessionId.value;
        controller?.abort();
        const hadSession = id !== null;
        reset();
        if (id === null) return;
        // Local cleanup first so a cancelled upload does not come back.
        await deleteStoredUploadSession(id);
        if (hadSession) {
            try {
                await deleteUploadSession(id);
            } catch {
                // Best effort: the Prefect cleanup flow purges the rest.
            }
        }
    }

    return {
        progress,
        state,
        sessionId,
        chunks,
        errorMessage,
        update,
        reset,
        beginChunked,
        attach,
        setSession,
        setState,
        setChunks,
        fail,
        pause,
        resume,
        cancel,
    };
});
