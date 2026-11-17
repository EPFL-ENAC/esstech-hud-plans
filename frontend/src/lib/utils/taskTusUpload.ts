import { DetailedError, Upload } from 'tus-js-client';
import { tusEndpoint } from 'src/boot/api';
import { ApiError } from 'src/lib/api';
import { getAccessToken, getAuthSubject } from 'src/lib/auth';
import type { FetchProgress } from './fetchProgress';

const UPLOAD_CHUNK_BYTES = 64 * 1024 * 1024;
const UPLOAD_RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];

export interface TusUploadResult {
    uploadId: string;
    uploadUrl: string;
    resumed: boolean;
}

export interface TaskTusUploadOptions {
    ownerId: string;
    uploadUrl: string | null;
    signal: AbortSignal;
    onCheckpoint: (uploadUrl: string) => Promise<void>;
    onProgress: (progress: FetchProgress) => void;
    onUploadAvailable: (upload: TusUploadResult) => void;
}

export async function uploadVideoTus(
    file: File,
    {
        ownerId,
        uploadUrl,
        signal,
        onCheckpoint,
        onProgress,
        onUploadAvailable,
    }: TaskTusUploadOptions,
): Promise<TusUploadResult> {
    signal.throwIfAborted();

    return new Promise((resolve, reject) => {
        let settled = false;
        let resumed = uploadUrl !== null;

        async function fail(error: unknown): Promise<void> {
            if (settled) return;

            // Suppress callbacks before stopping the transport.
            settled = true;
            signal.removeEventListener('abort', onAbort);

            try {
                // Pause locally without deleting the server upload.
                await upload.abort(false);
            } catch (cleanupError) {
                console.warn('Could not pause video upload', cleanupError);
            }

            reject(
                error instanceof Error ? error : new Error('Video upload failed', { cause: error }),
            );
        }

        function onAbort(): void {
            void fail(new DOMException('Aborted', 'AbortError'));
        }

        function isActive(): boolean {
            if (settled) return false;

            if (getAuthSubject() !== ownerId) {
                void fail(new ApiError('Upload account has changed', 401, null));
                return false;
            }

            return true;
        }

        function readResult(): TusUploadResult {
            if (!upload.url) {
                throw new Error('Upload has no location ID');
            }

            let location: URL;
            try {
                location = new URL(upload.url);
            } catch {
                throw new Error('Upload has an invalid location');
            }

            const uploadId = location.pathname.split('/').pop();
            if (!uploadId) {
                throw new Error('Upload has no location ID');
            }

            return {
                uploadId,
                uploadUrl: upload.url,
                resumed,
            };
        }

        const upload = new Upload(file, {
            endpoint: uploadUrl === null ? tusEndpoint : null,
            uploadUrl,
            chunkSize: UPLOAD_CHUNK_BYTES,
            retryDelays: UPLOAD_RETRY_DELAYS,
            metadata: {
                filename: file.name,
                filetype: file.type,
            },
            fingerprint: () => Promise.resolve(''),
            storeFingerprintForResuming: false,
            removeFingerprintOnSuccess: false,
            onBeforeRequest: (request) => {
                if (!isActive()) {
                    throw new DOMException('Aborted', 'AbortError');
                }

                if (request.getMethod() === 'HEAD') {
                    resumed = true;
                }

                // Read the current token for every request.
                const token = getAccessToken();
                if (token) {
                    request.setHeader('Authorization', `Bearer ${token}`);
                }
            },
            onAfterResponse: async (request, response) => {
                if (!isActive()) return;
                if (
                    request.getMethod() === 'POST' &&
                    response.getStatus() >= 200 &&
                    response.getStatus() < 300
                ) {
                    try {
                        const location = response.getHeader('Location');
                        if (!location) throw new Error('Upload has no location ID');
                        const url = new URL(location, request.getURL());
                        if (!url.pathname.split('/').pop())
                            throw new Error('Upload has no location ID');
                        await onCheckpoint(url.toString());
                    } catch (error) {
                        // Settle with the original persistence error, not Tus's wrapper.
                        await fail(error);
                        throw error;
                    }
                    if (!isActive()) throw new DOMException('Aborted', 'AbortError');
                }
            },
            onUploadUrlAvailable: () => {
                if (!isActive()) return;

                try {
                    const result = readResult();

                    // Tus must not create a replacement if resuming fails.
                    upload.options.endpoint = null;
                    onUploadAvailable(result);
                } catch (error) {
                    void fail(error);
                }
            },
            onProgress: (loaded, total) => {
                if (!isActive()) return;
                onProgress({ loaded, total });
            },
            onSuccess: () => {
                if (!isActive()) return;

                try {
                    const result = readResult();
                    settled = true;
                    signal.removeEventListener('abort', onAbort);
                    resolve(result);
                } catch (error) {
                    void fail(error);
                }
            },
            onError: (error) => {
                const failure =
                    error instanceof DetailedError
                        ? new ApiError(
                              `Upload failed: ${error.message}`,
                              error.originalResponse?.getStatus() ?? 0,
                              null,
                          )
                        : error;

                void fail(failure);
            },
        });

        signal.addEventListener('abort', onAbort, { once: true });

        // Cover interruption during transport construction.
        if (signal.aborted) {
            onAbort();
        } else if (isActive()) {
            try {
                upload.start();
            } catch (error) {
                void fail(error);
            }
        }
    });
}
