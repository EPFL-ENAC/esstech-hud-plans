import { DetailedError, Upload } from 'tus-js-client';
import { tusEndpoint } from 'src/boot/api';
import { getAccessToken } from 'src/lib/auth';
import { ApiError } from 'src/lib/buildings';
import type { FetchProgress } from './fetchProgress';

/**
 * Chunked, resumable video upload with the tus protocol against the tusd
 * sidecar. tusd keeps already-transferred bytes at the byte-offset level, so
 * a pause, a network drop, or a page reload continues from the last confirmed
 * offset without re-sending data.
 */
// Nothing buffers request bodies, so an unbounded chunk would also be valid;
// a fixed chunk keeps one failed request cheap on weak mobile uplinks.
const UPLOAD_CHUNK_BYTES = 64 * 1024 * 1024;

const UPLOAD_RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];

export interface ResumableUploadOptions {
    onProgress?: (progress: FetchProgress) => void;
    /** Called when a previously started upload is continued, before it starts. */
    onResumed?: () => void;
    signal?: AbortSignal;
}

export interface ResumableUploadResult {
    /** tusd-side upload id extracted from the upload location URL. */
    uploadId: string;
    /** True when a previously started upload of this file was continued. */
    resumed: boolean;
}

export function uploadVideoResumable(
    file: File,
    opts: ResumableUploadOptions = {},
): Promise<ResumableUploadResult> {
    return new Promise((resolve, reject) => {
        if (!tusEndpoint) {
            reject(new ApiError('Resumable upload endpoint is not configured', 0, null));
            return;
        }
        let resumed = false;
        const upload = new Upload(file, {
            endpoint: tusEndpoint,
            chunkSize: UPLOAD_CHUNK_BYTES,
            retryDelays: UPLOAD_RETRY_DELAYS,
            metadata: { filename: file.name, filetype: file.type },
            removeFingerprintOnSuccess: true,
            // Set the token per request, so a refresh during a long upload is
            // picked up by every PATCH.
            onBeforeRequest: (request) => {
                const token = getAccessToken();
                if (token) {
                    request.setHeader('Authorization', `Bearer ${token}`);
                }
            },
            onProgress: (bytesSent, bytesTotal) => {
                opts.onProgress?.({ loaded: bytesSent, total: bytesTotal ?? 0 });
            },
            onSuccess: () => {
                const uploadId = upload.url?.split('/').pop() ?? '';
                if (!uploadId) {
                    reject(new ApiError('Upload completed without a location', 0, null));
                    return;
                }
                resolve({ uploadId, resumed });
            },
            onError: (error) => {
                // A rejected pre-create hook surfaces as the forwarded HTTP status.
                const status =
                    error instanceof DetailedError ? (error.originalResponse?.getStatus() ?? 0) : 0;
                reject(new ApiError(`Upload failed: ${error.message}`, status, null));
            },
        });

        if (opts.signal) {
            opts.signal.addEventListener(
                'abort',
                () => {
                    // Pause: tusd keeps the transferred bytes and the
                    // fingerprint stays stored, so a later attempt resumes
                    // from the confirmed offset.
                    void upload.abort();
                    reject(new DOMException('Aborted', 'AbortError'));
                },
                { once: true },
            );
        }

        // Resume a previously started upload of this file after a reload; the
        // URL storage keeps one fingerprint per file, so a single match is the
        // upload this file belongs to.
        upload
            .findPreviousUploads()
            .then((previousUploads) => {
                // The signal may have aborted while the lookup was pending;
                // tus-js-client resets its aborted flag, so a stopped upload
                // must never be started here.
                if (opts.signal?.aborted) return;
                const previousUpload =
                    previousUploads.length === 1 ? previousUploads[0] : undefined;
                if (previousUpload) {
                    upload.resumeFromPreviousUpload(previousUpload);
                    resumed = true;
                    opts.onResumed?.();
                }
                upload.start();
            })
            .catch(() => {
                if (opts.signal?.aborted) return;
                upload.start();
            });
    });
}
