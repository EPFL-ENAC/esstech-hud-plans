import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';

/** States of the chunked splat download. */
export type SplatDownloadState =
    | 'idle'
    | 'downloading'
    | 'paused'
    | 'assembling'
    | 'done'
    | 'failed';

/** State machine of the splat .ply download shown while loading a splat. */
export const useSplatDownloadStore = defineStore('splatDownload', () => {
    /** null while idle or before the first progress event arrives. */
    const progress = ref<FetchProgress | null>(null);
    const state = ref<SplatDownloadState>('idle');
    const errorMessage = ref('');

    let controller: AbortController | null = null;
    let resumer: (() => void) | null = null;

    /** Kept for the plain-GET fallback path: record byte progress only. */
    function update(value: FetchProgress): void {
        progress.value = value;
    }

    function reset(): void {
        progress.value = null;
        state.value = 'idle';
        errorMessage.value = '';
        controller = null;
        resumer = null;
    }

    /** Start a chunked download pass with its own abort controller. */
    function beginChunked(nextController: AbortController): void {
        reset();
        controller = nextController;
        state.value = 'downloading';
    }

    /** Swap in a fresh controller after a paused pass was resumed. */
    function attach(nextController: AbortController): void {
        controller = nextController;
    }

    /** Set the function that restarts a paused download (a paused load). */
    function setResumer(nextResumer: () => void): void {
        resumer = nextResumer;
    }

    function setState(next: SplatDownloadState): void {
        state.value = next;
    }

    function fail(message: string): void {
        errorMessage.value = message;
        state.value = 'failed';
    }

    /** Abort in-flight range requests and wait for a resume. */
    function pause(): void {
        if (state.value !== 'downloading') return;
        controller?.abort();
        state.value = 'paused';
    }

    /** Let the paused download loop continue or restart a paused load. */
    function resume(): void {
        if (state.value !== 'paused') return;
        state.value = 'downloading';
        void resumer?.();
    }

    /** Cancel the download and drop its progress. */
    function cancel(): void {
        controller?.abort();
        reset();
    }

    return {
        progress,
        state,
        errorMessage,
        update,
        reset,
        beginChunked,
        attach,
        setResumer,
        setState,
        fail,
        pause,
        resume,
        cancel,
    };
});
