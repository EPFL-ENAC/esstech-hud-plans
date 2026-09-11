import { getAccessToken } from 'src/lib/auth';
import type { FetchProgress } from './fetchProgress';

/**
 * Upload a FormData body via XMLHttpRequest and report upload progress in
 * bytes. The browser fetch API cannot report upload progress, so this uses
 * `xhr.upload` progress events (true network bytes). Resolves with the HTTP
 * status and response text so callers can keep their error semantics.
 */
export function uploadWithProgress(
    url: string | URL,
    body: FormData,
    onProgress?: (progress: FetchProgress) => void,
    signal?: AbortSignal,
): Promise<{ status: number; text: string }> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        const token = getAccessToken();
        if (token) {
            // Do not set Content-Type: the browser appends the multipart boundary.
            xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        }
        if (signal) {
            const onAbort = (): void => xhr.abort();
            signal.addEventListener('abort', onAbort, { once: true });
            xhr.addEventListener('loadend', () => signal.removeEventListener('abort', onAbort));
        }
        xhr.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable) {
                onProgress?.({ loaded: event.loaded, total: event.total });
            }
        });
        xhr.addEventListener('load', () => resolve({ status: xhr.status, text: xhr.responseText }));
        xhr.addEventListener('error', () => reject(new Error('Upload request failed')));
        xhr.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        xhr.send(body);
    });
}
