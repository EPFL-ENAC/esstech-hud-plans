import { DetailedError, Upload } from 'tus-js-client';
import { tusEndpoint } from 'src/boot/api';
import { getAccessToken, getAuthSubject } from 'src/lib/auth';
import { ApiError } from 'src/lib/api';
import type { FetchProgress } from './fetchProgress';

/**
 * Chunked, resumable video upload with the tus protocol through the API
 * upload proxy, which forwards the requests to the tusd server. tusd keeps
 * already-transferred bytes at the byte-offset level, so
 * a pause, a network drop, or a page reload continues from the last confirmed
 * offset without re-sending data.
 */
// Nothing buffers request bodies, so an unbounded chunk would also be valid;
// a fixed chunk keeps one failed request cheap on weak mobile uplinks.
const UPLOAD_CHUNK_BYTES = 64 * 1024 * 1024;

const UPLOAD_RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];
const activeUploadUrls = new Set<string>();

export interface ResumableUploadOptions {
    onProgress?: (progress: FetchProgress) => void;
    /** Called when a previously started upload is continued, before it starts. */
    onResumed?: () => void;
    /** Called after creation or validated resume, before the transfer completes. */
    onUploadAvailable?: (uploadId: string) => void;
    signal?: AbortSignal;
    /** Scope resume records and requests to this account. */
    subject?: string;
}

export interface ResumableUploadResult {
    /** Application upload ID extracted from the proxied upload location URL. */
    uploadId: string;
    /** True when a previously started upload of this file was continued. */
    resumed: boolean;
}

export function uploadVideoResumable(
    file: File,
    opts: ResumableUploadOptions = {},
): Promise<ResumableUploadResult> {
    return new Promise((resolve, reject) => {
        if (opts.signal?.aborted) {
            reject(new DOMException('Aborted', 'AbortError'));
            return;
        }
        let settled = false;
        let resumed = false;
        let reservedUrl: string | null = null;

        function finish(settle: () => void): void {
            if (settled) return;
            settled = true;
            if (reservedUrl) activeUploadUrls.delete(reservedUrl);
            opts.signal?.removeEventListener('abort', onAbort);
            settle();
        }

        function pause(): void {
            // Pause without deleting the upload or its resume fingerprint.
            try {
                void upload.abort(false).catch((error: unknown) => {
                    console.warn('Could not pause video upload', error);
                });
            } catch (error) {
                console.warn('Could not pause video upload', error);
            }
        }

        function onAbort(): void {
            if (settled) return;
            finish(() => reject(new DOMException('Aborted', 'AbortError')));
            pause();
        }

        function requireAccount(): void {
            if (opts.subject === undefined || getAuthSubject() === opts.subject) return;
            const error = new ApiError('Upload account has changed', 401, null);
            finish(() => reject(error));
            pause();
            throw error;
        }

        function reserveUrl(url: string | null): void {
            if (!url || url === reservedUrl) return;
            if (activeUploadUrls.has(url)) {
                throw new ApiError('Upload is already active', 409, null);
            }
            if (reservedUrl) activeUploadUrls.delete(reservedUrl);
            activeUploadUrls.add(url);
            reservedUrl = url;
        }

        const upload = new Upload(file, {
            endpoint: tusEndpoint,
            chunkSize: UPLOAD_CHUNK_BYTES,
            retryDelays: UPLOAD_RETRY_DELAYS,
            metadata: { filename: file.name, filetype: file.type },
            removeFingerprintOnSuccess: true,
            ...(opts.subject === undefined
                ? {}
                : {
                      fingerprint: () =>
                          Promise.resolve(
                              JSON.stringify([
                                  'hud-upload',
                                  opts.subject,
                                  tusEndpoint,
                                  file.name,
                                  file.type,
                                  file.size,
                                  file.lastModified,
                              ]),
                          ),
                  }),
            // Set the token per request, so a refresh during a long upload is
            // picked up by every PATCH.
            onBeforeRequest: (request) => {
                if (settled) throw new DOMException('Aborted', 'AbortError');
                requireAccount();
                const token = getAccessToken();
                if (token) {
                    request.setHeader('Authorization', `Bearer ${token}`);
                }
            },
            onUploadUrlAvailable: () => {
                if (settled) return;
                requireAccount();
                const uploadId = upload.url?.split('/').pop() ?? '';
                if (!uploadId) {
                    finish(() => reject(new ApiError('Upload has no location ID', 0, null)));
                    pause();
                    return;
                }
                reserveUrl(upload.url);
                opts.onUploadAvailable?.(uploadId);
            },
            onProgress: (bytesSent, bytesTotal) => {
                if (settled) return;
                opts.onProgress?.({ loaded: bytesSent, total: bytesTotal ?? 0 });
            },
            onSuccess: () => {
                if (settled) return;
                const uploadId = upload.url?.split('/').pop() ?? '';
                if (!uploadId) {
                    finish(() =>
                        reject(new ApiError('Upload completed without a location', 0, null)),
                    );
                    return;
                }
                finish(() => resolve({ uploadId, resumed }));
            },
            onError: (error) => {
                // A rejected pre-create hook surfaces as the forwarded HTTP status.
                const status =
                    error instanceof DetailedError ? (error.originalResponse?.getStatus() ?? 0) : 0;
                finish(() => reject(new ApiError(`Upload failed: ${error.message}`, status, null)));
            },
        });

        opts.signal?.addEventListener('abort', onAbort, { once: true });

        async function startUpload(): Promise<void> {
            let previousUploads: Awaited<ReturnType<Upload['findPreviousUploads']>> = [];
            try {
                previousUploads = await upload.findPreviousUploads();
            } catch {
                // Unavailable resume storage must not prevent a fresh upload.
            }
            // tus-js-client resets its aborted flag on start, so a pending
            // lookup must never restart an upload that already settled.
            if (settled) return;
            requireAccount();
            const availableUploads = previousUploads.filter(
                (previous) => !previous.uploadUrl || !activeUploadUrls.has(previous.uploadUrl),
            );
            const previousUpload = availableUploads.length === 1 ? availableUploads[0] : undefined;
            if (previousUpload) {
                reserveUrl(previousUpload.uploadUrl);
                upload.resumeFromPreviousUpload(previousUpload);
                resumed = true;
                opts.onResumed?.();
            }
            if (!settled) upload.start();
        }

        // Also cover a signal aborted during setup, before the listener existed.
        if (opts.signal?.aborted) onAbort();
        else {
            void startUpload().catch((error: unknown) => {
                const failure =
                    error instanceof Error
                        ? error
                        : new Error('Could not start video upload', { cause: error });
                finish(() => reject(failure));
            });
        }
    });
}
