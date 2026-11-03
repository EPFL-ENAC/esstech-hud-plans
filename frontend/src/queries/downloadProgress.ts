import type { PiniaColadaPlugin, UseQueryEntry } from '@pinia/colada';
import { shallowRef, type ShallowRef } from 'vue';
import type { FetchProgress } from 'src/lib/utils/fetchProgress';

declare module '@pinia/colada' {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Colada requires matching generic parameters.
    interface UseQueryEntryExtensions<TData, TError, TDataInitial> {
        downloadProgress: ShallowRef<FetchProgress | null>;
    }
}

/** Progress belongs to the same cache entry as the downloaded resource. */
export function PiniaColadaDownloadProgress(): PiniaColadaPlugin {
    return ({ queryCache, scope }) => {
        queryCache.$onAction(({ name, args }) => {
            if (name !== 'extend') return;
            const [entry] = args;
            scope.run(() => {
                entry.ext.downloadProgress = shallowRef<FetchProgress | null>(null);
            });
        });
    };
}

export function trackDownloadProgress(
    entry: UseQueryEntry,
    signal: AbortSignal,
): (progress: FetchProgress) => void {
    entry.ext.downloadProgress.value = null;
    return (progress) => {
        if (!signal.aborted) entry.ext.downloadProgress.value = progress;
    };
}
