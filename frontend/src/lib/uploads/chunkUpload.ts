import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/buildings';
import type { ChunkPlanEntry } from './fileDigest';

/** Server chunk size, mirrored from UPLOAD_CHUNK_SIZE_BYTES in api/config.py. */
export const UPLOAD_CHUNK_SIZE_BYTES = 8_388_608;

/** Videos at or under one chunk keep the single-shot multipart path. */
export const SMALL_FILE_THRESHOLD = UPLOAD_CHUNK_SIZE_BYTES;
export const PUT_CONCURRENCY = 2;
export const UPLOAD_RETRY_ATTEMPTS = 3;
export const UPLOAD_RETRY_BACKOFF_MS = 1000;

export interface UploadSessionCreatePayload {
    filename: string;
    total_size: number;
    chunk_size: number;
    settings: unknown;
    chunks: Array<{ index: number; size: number; sha256: string }>;
    building_id?: string;
    building?: unknown;
}

/** Response body of POST /uploads. */
export interface UploadSessionCreateResponse {
    session_id: string;
    chunk_size: number;
    total_chunks: number;
    expires_at: string;
    missing_chunks: number[];
}

/** Response body of GET /uploads/{session_id}. */
export interface UploadSessionStateResponse {
    status: string;
    chunk_size: number;
    total_chunks: number;
    received_bytes: number;
    missing_chunks: number[];
    expires_at: string;
}

/** Response body of PUT /uploads/{session_id}/chunks/{index}. */
export interface ChunkPutResult {
    received_bytes: number;
    missing_chunks_count: number;
}

/**
 * Attach the abort signal to a fetch init only when it exists. Required by
 * exactOptionalPropertyTypes, which rejects a signal: AbortSignal | undefined
 * property for an optional target property.
 */
function withSignal(init: RequestInit, signal?: AbortSignal): RequestInit {
    return signal ? { ...init, signal } : init;
}

async function requestJson<T>(url: string, init: RequestInit): Promise<T> {
    const response = await authFetch(`${baseUrl}${url}`, init);
    const text = await response.text();
    let body: unknown = null;
    if (text) {
        try {
            body = JSON.parse(text) as unknown;
        } catch {
            body = text;
        }
    }
    if (!response.ok) {
        throw new ApiError(`Request failed with HTTP ${response.status}`, response.status, body);
    }
    return body as T;
}

/** Create an upload session against POST /uploads. */
export function createUploadSession(
    payload: UploadSessionCreatePayload,
    signal?: AbortSignal,
): Promise<UploadSessionCreateResponse> {
    return requestJson<UploadSessionCreateResponse>(
        '/uploads',
        withSignal(
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            },
            signal,
        ),
    );
}

/** Read the session state. Used to resume after a pause or a page reload. */
export function fetchUploadSession(
    sessionId: string,
    signal?: AbortSignal,
): Promise<UploadSessionStateResponse> {
    return requestJson<UploadSessionStateResponse>(
        `/uploads/${encodeURIComponent(sessionId)}`,
        withSignal({}, signal),
    );
}

/** Client-side cancel: the backend removes the temp dir and the rows. */
export async function deleteUploadSession(sessionId: string, signal?: AbortSignal): Promise<void> {
    const response = await authFetch(
        `${baseUrl}/uploads/${encodeURIComponent(sessionId)}`,
        withSignal({ method: 'DELETE' }, signal),
    );
    if (!response.ok) {
        throw new ApiError(
            `Request failed with HTTP ${response.status}`,
            response.status,
            await response.text(),
        );
    }
}

/** Finalize the session. Returns the reconstruction (or building + reconstruction). */
export function finalizeUploadSession(sessionId: string, signal?: AbortSignal): Promise<unknown> {
    return requestJson<unknown>(
        `/uploads/${encodeURIComponent(sessionId)}/finalize`,
        withSignal({ method: 'POST' }, signal),
    );
}

/**
 * Diff the server missing list against the plan: the PUT queue is the sorted
 * subset of planned chunks the server still misses.
 */
export function computePutQueue(plan: ChunkPlanEntry[], missingChunks: number[]): ChunkPlanEntry[] {
    const missing = new Set(missingChunks);
    return plan.filter((entry) => missing.has(entry.index));
}

/** Indices still to send after a partial pass, in plan order. */
export function remainingChunkIndices(entries: ChunkPlanEntry[], sent: number[]): number[] {
    const sentSet = new Set(sent);
    return entries.filter((entry) => !sentSet.has(entry.index)).map((entry) => entry.index);
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

async function putOnce(
    sessionId: string,
    entry: ChunkPlanEntry,
    file: File,
    signal: AbortSignal,
): Promise<ChunkPutResult> {
    const slice = file.slice(entry.offset, entry.offset + entry.size);
    return requestJson<ChunkPutResult>(
        `/uploads/${encodeURIComponent(sessionId)}/chunks/${entry.index}`,
        {
            method: 'PUT',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: slice,
            signal,
        },
    );
}

export interface UploadChunksOptions {
    sessionId: string;
    file: File;
    entries: ChunkPlanEntry[];
    signal: AbortSignal;
    /** Bytes already on the server before this run, for progress math. */
    receivedBytes: number;
    onProgress?: (progress: { loaded: number; total: number }) => void;
    onChunkDone?: (index: number) => void;
}

/**
 * PUT the queued chunks in parallel with a bounded concurrency of 2. Each
 * chunk retries up to UPLOAD_RETRY_ATTEMPTS times with a growing backoff so
 * one flaky chunk does not lose the whole pass.
 */
export async function uploadSessionChunks(options: UploadChunksOptions): Promise<void> {
    const { sessionId, file, entries, signal, receivedBytes, onProgress, onChunkDone } = options;
    let loaded = receivedBytes;
    let next = 0;
    let stopped = false;

    const worker = async (): Promise<void> => {
        for (;;) {
            if (stopped) return;
            const current = next;
            if (current >= entries.length) return;
            next++;

            const entry = entries[current];
            if (entry === undefined) return;
            let lastError: unknown = null;
            for (let attempt = 0; attempt < UPLOAD_RETRY_ATTEMPTS; attempt++) {
                if (attempt > 0) {
                    await delay(UPLOAD_RETRY_BACKOFF_MS * attempt, signal);
                }
                try {
                    await putOnce(sessionId, entry, file, signal);
                    loaded = Math.min(loaded + entry.size, file.size);
                    onProgress?.({ loaded, total: file.size });
                    onChunkDone?.(entry.index);
                    lastError = null;
                    break;
                } catch (error) {
                    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
                    if (error instanceof ApiError && error.status < 500) {
                        // Deterministic 4xx responses never change on retry.
                        stopped = true;
                        throw error;
                    }
                    lastError = error;
                }
            }

            if (lastError !== null) {
                stopped = true;
                throw lastError instanceof Error
                    ? lastError
                    : new Error(
                          typeof lastError === 'string'
                              ? lastError
                              : 'Chunk upload failed after retries',
                      );
            }
        }
    };

    await Promise.all(
        Array.from({ length: Math.min(PUT_CONCURRENCY, entries.length) }, () => worker()),
    );
}
