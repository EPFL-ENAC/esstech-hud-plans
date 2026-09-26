import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/buildings';
import { downloadWithProgress } from 'src/lib/utils/fetchProgress';
import {
    deleteDownloadData,
    downloadChunkId,
    getDownloadChunk,
    getDownloadMeta,
    probeIndexedDb,
    requestPersistentStorage,
    saveDownloadChunk,
    saveDownloadMeta,
} from '../localTransfers';

/**
 * Byte size of one stored download chunk and one range request. Small stream
 * reads keep renderer memory flat while one Blob per range chunk is stored.
 */
export const DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024;
export const DOWNLOAD_READ_BYTES = 128 * 1024;
const RETRY_ATTEMPTS = 3;
const RETRY_BACKOFF_MS = 800;
/** Passes through the state machine before an incomplete download fails. */
const MAX_PASSES = 2;

export interface DownloadProgressResult {
    loaded: number; // bytes
    total: number; // bytes
}

/** Decision of the chunked download state machine for one response status. */
export type RangeDecision = 'append' | 'reset' | 'restart' | 'error';

/**
 * 206 appends, 200 means the server ignored the Range or If-Range request or
 * the file changed under the etag, 416 means the offset is invalid or the
 * file changed, anything else is a terminal server error.
 */
export function nextRangeDecision(status: number): RangeDecision {
    if (status === 206) return 'append';
    if (status === 200) return 'reset';
    if (status === 416) return 'restart';
    return 'error';
}

/** Single closed range form, which stays CORS-preflight free. */
export function rangeHeaderValue(offset: number, total: number): string {
    const end =
        total > 0
            ? Math.min(offset + DOWNLOAD_CHUNK_BYTES, total) - 1
            : offset + DOWNLOAD_CHUNK_BYTES - 1;
    return `bytes=${offset}-${end}`;
}

export function chunkIndexForOffset(offset: number): number {
    return Math.floor(offset / DOWNLOAD_CHUNK_BYTES);
}

interface ContentRangeInfo {
    start: number;
    end: number;
    total: number;
}

/** Parse `bytes start-end/total` from a 206 response header. */
export function parseContentRange(value: string | null): ContentRangeInfo | null {
    if (value === null) return null;
    const match = /^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/.exec(value.trim());
    if (!match) return null;
    return {
        start: Number(match[1]),
        end: Number(match[2]),
        total: match[3] === '*' ? 0 : Number(match[3]),
    };
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve(), ms);
        signal.addEventListener(
            'abort',
            () => {
                clearTimeout(timer);
                reject(new DOMException('Aborted', 'AbortError'));
            },
            { once: true },
        );
    });
}

class RangeRestartError extends Error {
    constructor() {
        super('Range request rejected; restart the download');
    }
}

interface DownloadContext {
    url: string;
    key: string;
    signal: AbortSignal;
    onProgress?: (progress: DownloadProgressResult) => void;
    etag: string | null;
    total: number;
    received: number;
    restarts: number;
}

function throwIfAborted(signal: AbortSignal): void {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
}

function storeChunk(context: DownloadContext, blob: Blob): Promise<void> {
    const index = chunkIndexForOffset(context.received);
    const size = blob.size;
    return saveDownloadChunk({
        id: downloadChunkId(context.key, index),
        key: context.key,
        index,
        blob,
        size,
    }).then(() => {
        // The offset advances only after the chunk write resolves, so a
        // failed save retries the same range instead of skipping bytes.
        context.received += size;
        return saveDownloadMeta({
            key: context.key,
            url: context.url,
            total: context.total,
            etag: context.etag,
            receivedBytes: context.received,
        });
    });
}

/**
 * Read one response body and store its bytes as chunk Blobs. Range bodies
 * hold at most one chunk; a degraded full-body read splits at chunk bounds.
 */
async function readBodyIntoChunks(context: DownloadContext, response: Response): Promise<void> {
    let parts: BlobPart[] = [];
    let bucketSize = 0;
    const flush = async (): Promise<void> => {
        const blob = new Blob(parts);
        parts = [];
        bucketSize = 0;
        await storeChunk(context, blob);
        context.onProgress?.({ loaded: context.received, total: context.total });
    };

    if (response.body === null) {
        const body = await response.arrayBuffer();
        context.total = context.total || body.byteLength;
        await storeChunk(context, new Blob([body]));
        context.onProgress?.({ loaded: context.received, total: context.total });
        return;
    }

    const reader = response.body.getReader();
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value) continue;
        let cursor = 0;
        while (cursor < value.byteLength) {
            const take = Math.min(value.byteLength - cursor, DOWNLOAD_CHUNK_BYTES - bucketSize);
            parts.push(value.subarray(cursor, cursor + take));
            cursor += take;
            bucketSize += take;
            if (bucketSize === DOWNLOAD_CHUNK_BYTES) {
                await flush();
            } else {
                context.onProgress?.({
                    loaded: context.received + bucketSize,
                    total: context.total,
                });
            }
        }
    }
    if (bucketSize > 0) {
        await flush();
    }
    if (context.total === 0) {
        context.total = context.received;
        await saveDownloadMeta({
            key: context.key,
            url: context.url,
            total: context.total,
            etag: context.etag,
            receivedBytes: context.received,
        });
    }
}

async function restartFromScratch(context: DownloadContext): Promise<void> {
    if (context.restarts >= 1) {
        throw new ApiError('The server rejected the range request', 416, null);
    }
    context.restarts++;
    await deleteDownloadData(context.key);
    context.total = 0;
    context.etag = null;
    context.received = 0;
}

/**
 * One pass of the state machine: request the next missing range, handle the
 * 206/200/416 decision, and retry network failures within one range.
 */
async function runRangeLoop(context: DownloadContext): Promise<ArrayBuffer | null> {
    for (;;) {
        throwIfAborted(context.signal);
        if (context.total > 0 && context.received >= context.total) return null;

        const headers: Record<string, string> = {
            Range: rangeHeaderValue(context.received, context.total),
        };
        if (context.received > 0 && context.etag !== null) {
            headers['If-Range'] = context.etag;
        }

        for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                await delay(RETRY_BACKOFF_MS * attempt, context.signal);
                throwIfAborted(context.signal);
            }
            try {
                const response = await authFetch(context.url, {
                    headers,
                    signal: context.signal,
                });
                const acceptRanges = response.headers.get('accept-ranges');
                if (
                    context.received === 0 &&
                    context.total === 0 &&
                    response.status === 200 &&
                    (acceptRanges === null || acceptRanges.trim().toLowerCase() === 'none')
                ) {
                    // The server cannot serve ranges: use the plain
                    // accumulating download instead of the chunk stores.
                    return downloadWithProgress(
                        context.url,
                        { signal: context.signal },
                        context.onProgress,
                    );
                }
                const decision = nextRangeDecision(response.status);
                if (decision === 'error') {
                    throw new ApiError(
                        `Request failed with HTTP ${response.status}`,
                        response.status,
                        null,
                    );
                }
                if (decision === 'restart') {
                    await restartFromScratch(context);
                    return null;
                }

                const info = parseContentRange(response.headers.get('content-range'));
                if (info && info.start !== context.received) {
                    throw new RangeRestartError();
                }
                if (decision === 'append' && info !== null && info.total > 0) {
                    context.total = info.total;
                }
                const etagHeader = response.headers.get('etag');
                if (etagHeader !== null) context.etag = etagHeader;

                if (decision === 'reset') {
                    // The server ignored the range, so the body starts at
                    // byte 0: drop stored chunks and stream the full body.
                    await deleteDownloadData(context.key);
                    context.received = 0;
                    context.total = 0;
                }
                await readBodyIntoChunks(context, response);
                return null;
            } catch (error) {
                if (context.signal.aborted) {
                    throw new DOMException('Aborted', 'AbortError');
                }
                if (error instanceof RangeRestartError) {
                    await restartFromScratch(context);
                    return null;
                }
                if (error instanceof ApiError) throw error;
                // keep lastError and retry the same range
            }
        }
        throw new Error('Download request failed repeatedly');
    }
}

/** Read every stored chunk in order into one buffer. */
async function assembleStoredChunks(key: string, total: number): Promise<ArrayBuffer | null> {
    if (total <= 0) return null;
    const count = Math.ceil(total / DOWNLOAD_CHUNK_BYTES);
    const buffer = new Uint8Array(total);
    let position = 0;
    for (let index = 0; index < count; index++) {
        const chunk = await getDownloadChunk(key, index);
        if (chunk === null) return null;
        const bytes = await chunk.blob.arrayBuffer();
        buffer.set(new Uint8Array(bytes), position);
        position += bytes.byteLength;
    }
    if (position !== total) return null;
    return buffer.buffer;
}

export interface ChunkedDownloadOptions {
    url: string;
    key: string;
    signal: AbortSignal;
    onProgress?: (progress: DownloadProgressResult) => void;
}

/**
 * Chunked GET with resume. State lives in IndexedDB, so a pause, a page
 * reload, or an app restart continues from the stored offset, and finished
 * chunks only need storage. Storage-capable browsers stream; others fall
 * back to the plain-GET accumulating path.
 */
export async function chunkedDownload(options: ChunkedDownloadOptions): Promise<ArrayBuffer> {
    const { url, key, signal, onProgress } = options;
    const storageReady = await probeIndexedDb();
    if (!storageReady) {
        return downloadWithProgress(url, { signal }, onProgress);
    }
    void requestPersistentStorage();

    const context: DownloadContext = {
        url,
        key,
        signal,
        ...(onProgress ? { onProgress } : {}),
        etag: null,
        total: 0,
        received: 0,
        restarts: 0,
    };
    const meta = await getDownloadMeta(key);
    if (meta !== null) {
        if (meta.url !== url) {
            await deleteDownloadData(key);
        } else {
            context.etag = meta.etag;
            context.total = meta.total;
            context.received = meta.receivedBytes;
        }
    }

    for (let attempt = 0; attempt < MAX_PASSES; attempt++) {
        const fallback = await runRangeLoop(context);
        if (fallback !== null) {
            return fallback;
        }
        const buffer = await assembleStoredChunks(key, context.total);
        if (buffer !== null) {
            void deleteDownloadData(key);
            return buffer;
        }
        // Stored chunks are incomplete (evicted mid-download): redo once.
        await deleteDownloadData(key);
        context.total = 0;
        context.etag = null;
        context.received = 0;
    }
    throw new ApiError('Download chunks are incomplete', 503, null);
}

export interface SplatDownloadOptions {
    buildingId: string;
    reconstructionId: string;
    signal: AbortSignal;
    onProgress?: (progress: DownloadProgressResult) => void;
}

/**
 * Chunked download of one reconstruction splat. The URL mirrors
 * getReconstructionSplat in lib/buildings.ts, keyed for resume storage.
 */
export function downloadSplatChunked(
    buildingId: string,
    reconstructionId: string,
    signal: AbortSignal,
    onProgress?: (progress: DownloadProgressResult) => void,
): Promise<ArrayBuffer> {
    const url = `${baseUrl}/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/splat`;
    const key = `splat:${buildingId}:${reconstructionId}`;
    return chunkedDownload({ url, key, signal, ...(onProgress ? { onProgress } : {}) });
}
