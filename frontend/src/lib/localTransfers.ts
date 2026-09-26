import { watch } from 'vue';
import type { FileFingerprint } from './uploads/fileDigest';

/** Names of the IndexedDB stores of this app's transfer storage. */
export const TRANSFER_DB_NAME = 'esstech-hud-transfers';
export const TRANSFER_DB_VERSION = 1;
export const UPLOAD_SESSION_STORE = 'uploadSessions';
export const DOWNLOAD_CHUNK_STORE = 'downloadChunks';

/** Stored upload records live past the server session TTL, then expire. */
export const UPLOAD_RECORD_MAX_AGE_MS = 72 * 60 * 60 * 1000;

/** One stored upload attempt. The file blob lets a paused page resume. */
export interface StoredUploadSession {
    sessionId: string;
    file: Blob;
    plan: Array<{ index: number; offset: number; size: number; sha256: string }>;
    fingerprint: { name: string; size: number; lastModified: number };
    updatedAt: number;
}

/** One stored download chunk. */
export interface StoredDownloadChunk {
    id: string; // `${key}:${index}`
    key: string;
    index: number;
    blob: Blob;
    size: number;
}

/** Resume metadata of one chunked download. */
export interface StoredDownloadMeta {
    key: string;
    url: string;
    total: number;
    etag: string | null;
    receivedBytes: number;
}

function indexedDb(): IDBFactory | null {
    const factory = globalThis.indexedDB;
    return typeof globalThis.indexedDB === 'object' && factory !== null ? factory : null;
}

/**
 * Best-effort persistent storage request. Safari may delete script-writable
 * storage after seven days without use, so the first chunked download asks.
 */
export async function requestPersistentStorage(): Promise<void> {
    try {
        await globalThis.navigator?.storage?.persist?.();
    } catch {
        // Storage persistence is best effort; the transfer never blocks on it.
    }
}

function openTransferDatabase(): Promise<IDBDatabase | null> {
    const factory = indexedDb();
    if (factory === null) return Promise.resolve(null);
    return new Promise((resolve, reject) => {
        try {
            const request = factory.open(TRANSFER_DB_NAME, TRANSFER_DB_VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                if (!db.objectStoreNames.contains(UPLOAD_SESSION_STORE)) {
                    db.createObjectStore(UPLOAD_SESSION_STORE, { keyPath: 'sessionId' });
                }
                if (!db.objectStoreNames.contains(DOWNLOAD_CHUNK_STORE)) {
                    db.createObjectStore(DOWNLOAD_CHUNK_STORE, { keyPath: 'id' });
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed'));
            request.onblocked = () => reject(new Error('IndexedDB open blocked'));
        } catch (error) {
            reject(error instanceof Error ? error : new Error('IndexedDB open failed'));
        }
    });
}

/**
 * One-shot capability probe. Opens the transfer database and closes it. A
 * private browsing mode or an old device can throw or return no factory, so
 * callers treat a false result as the plain-GET fallback signal.
 */
export async function probeIndexedDb(): Promise<boolean> {
    try {
        const db = await openTransferDatabase();
        if (db === null) return false;
        db.close();
        return true;
    } catch {
        return false;
    }
}

async function withStore<T>(
    storeName: string,
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => IDBRequest<T> | void,
): Promise<T | null> {
    let db: IDBDatabase | null = null;
    try {
        db = await openTransferDatabase();
        if (db === null) return null;
        const database = db;
        return await new Promise<T | null>((resolve, reject) => {
            const transaction = database.transaction(storeName, mode);
            const store = transaction.objectStore(storeName);
            let result: T | null = null;
            let request: IDBRequest<T> | void;
            try {
                request = run(store);
            } catch (error) {
                reject(error instanceof Error ? error : new Error('IndexedDB request failed'));
                return;
            }
            if (request) {
                request.onsuccess = () => {
                    result = request.result;
                };
            }
            transaction.oncomplete = () => resolve(result);
            transaction.onerror = () =>
                reject(transaction.error ?? new Error('IndexedDB transaction failed'));
            transaction.onabort = () =>
                reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
        });
    } catch {
        // Storage failures (private mode, eviction, old device) are not fatal
        // for the transfer itself; callers fall back to non-resumable paths.
        return null;
    } finally {
        db?.close();
    }
}

export async function saveUploadSession(record: StoredUploadSession): Promise<void> {
    await withStore(UPLOAD_SESSION_STORE, 'readwrite', (store) => {
        store.put(record);
        return undefined;
    });
}

export async function getUploadSession(sessionId: string): Promise<StoredUploadSession | null> {
    return withStore<StoredUploadSession>(UPLOAD_SESSION_STORE, 'readonly', (store) =>
        store.get(sessionId),
    );
}

export async function deleteUploadSession(sessionId: string): Promise<void> {
    await withStore(UPLOAD_SESSION_STORE, 'readwrite', (store) => {
        store.delete(sessionId);
        return undefined;
    });
}

/**
 * Find the newest stored upload record with the given video fingerprint.
 * Used to resume an upload after a page reload or a restart.
 */
export async function findUploadSessionByFingerprint(
    fingerprint: FileFingerprint,
): Promise<StoredUploadSession | null> {
    const records = await withStore<StoredUploadSession[]>(
        UPLOAD_SESSION_STORE,
        'readonly',
        (store) => store.getAll() as IDBRequest<StoredUploadSession[]>,
    );
    if (!records) return null;
    const matched = records.filter(
        (record) =>
            typeof record.sessionId === 'string' &&
            Array.isArray(record.plan) &&
            record.fingerprint?.name === fingerprint.name &&
            record.fingerprint?.size === fingerprint.size &&
            record.fingerprint?.lastModified === fingerprint.lastModified,
    );
    if (matched.length === 0) return null;
    return matched.reduce((newest, record) =>
        record.updatedAt > newest.updatedAt ? record : newest,
    );
}

/** Refresh the stored record time so eviction keeps live sessions. */
export async function touchUploadSession(sessionId: string): Promise<void> {
    const record = await getUploadSession(sessionId);
    if (record === null) return;
    await saveUploadSession({ ...record, updatedAt: Date.now() });
}

export function downloadChunkId(key: string, index: number): string {
    return `${key}:${index}`;
}

export async function saveDownloadChunk(chunk: StoredDownloadChunk): Promise<void> {
    await withStore(DOWNLOAD_CHUNK_STORE, 'readwrite', (store) => {
        store.put(chunk);
        return undefined;
    });
}

export async function saveDownloadChunks(
    key: string,
    chunks: StoredDownloadChunk[],
): Promise<void> {
    await withStore(DOWNLOAD_CHUNK_STORE, 'readwrite', (store) => {
        for (const chunk of chunks) store.put(chunk);
        return undefined;
    });
}

export async function getDownloadChunk(
    key: string,
    index: number,
): Promise<StoredDownloadChunk | null> {
    return withStore<StoredDownloadChunk>(
        DOWNLOAD_CHUNK_STORE,
        'readonly',
        (store) => store.get(downloadChunkId(key, index)) as IDBRequest<StoredDownloadChunk>,
    );
}

/** Byte total of the stored chunks of one download key. */
export async function getDownloadStoredBytes(key: string): Promise<number> {
    const stored = await withStore<StoredDownloadChunk[]>(
        DOWNLOAD_CHUNK_STORE,
        'readonly',
        (store) =>
            store.getAll(IDBKeyRange.bound(`${key}:`, `${key}:\uffff`)) as IDBRequest<
                StoredDownloadChunk[]
            >,
    );
    if (!stored) return 0;
    return stored.reduce((sum, chunk) => sum + chunk.size, 0);
}

export async function listDownloadChunks(key: string): Promise<StoredDownloadChunk[]> {
    return (
        (await withStore<StoredDownloadChunk[]>(
            DOWNLOAD_CHUNK_STORE,
            'readonly',
            (store) =>
                store.getAll(IDBKeyRange.bound(`${key}:`, `${key}:\uffff`)) as IDBRequest<
                    StoredDownloadChunk[]
                >,
        )) ?? []
    );
}

export async function saveDownloadMeta(meta: StoredDownloadMeta): Promise<void> {
    await withStore(UPLOAD_SESSION_STORE, 'readwrite', (store) => {
        store.put({ sessionId: `download-meta:${meta.key}`, ...meta });
        return undefined;
    });
}

export async function getDownloadMeta(key: string): Promise<StoredDownloadMeta | null> {
    const record = await withStore<StoredDownloadMeta & { sessionId: string }>(
        UPLOAD_SESSION_STORE,
        'readonly',
        (store) =>
            store.get(`download-meta:${key}`) as IDBRequest<
                StoredDownloadMeta & { sessionId: string }
            >,
    );
    if (!record) return null;
    return {
        key: record.key,
        url: record.url,
        total: record.total,
        etag: record.etag,
        receivedBytes: record.receivedBytes,
    };
}

export async function deleteDownloadData(key: string): Promise<void> {
    await withStore(DOWNLOAD_CHUNK_STORE, 'readwrite', (store) => {
        store.delete(IDBKeyRange.bound(`${key}:`, `${key}:\uffff`));
        return undefined;
    });
    await withStore(UPLOAD_SESSION_STORE, 'readwrite', (store) => {
        store.delete(`download-meta:${key}`);
        return undefined;
    });
}

/** Drop stored upload records older than the given age. Call at app start. */
export async function evictStaleUploadSessions(maxAgeMs: number): Promise<void> {
    const now = Date.now();
    await withStore(UPLOAD_SESSION_STORE, 'readwrite', (store) => {
        const request = store.openCursor();
        request.onsuccess = () => {
            const cursor = request.result;
            if (!cursor) return;
            const value = cursor.value as StoredUploadSession;
            if (now - value.updatedAt > maxAgeMs) cursor.delete();
            cursor.continue();
        };
    });
}

/**
 * Wait until a paused transfer leaves the paused state. Resume states count
 * as a resume; idle or failed states count as a cancellation so the caller
 * can clean its session. An optional stop signal (a query cancel) ends the
 * wait as a cancellation.
 */
export function waitForResume(
    currentState: () => string,
    stopSignal?: AbortSignal,
): Promise<'resumed' | 'cancelled'> {
    return new Promise((resolve) => {
        let stopWatcher: (() => void) | null = null;
        let settled = false;
        const finish = (value: 'resumed' | 'cancelled') => {
            if (settled) return;
            settled = true;
            stopWatcher?.();
            resolve(value);
        };
        // immediate: true resolves the race where the state already left the
        // paused state before the watcher was created.
        stopWatcher = watch(
            currentState,
            (next) => {
                if (next === 'paused') return;
                finish(next === 'uploading' || next === 'downloading' ? 'resumed' : 'cancelled');
            },
            { immediate: true },
        );
        if (settled) stopWatcher();
        if (stopSignal) {
            stopSignal.addEventListener('abort', () => finish('cancelled'), { once: true });
        }
    });
}
