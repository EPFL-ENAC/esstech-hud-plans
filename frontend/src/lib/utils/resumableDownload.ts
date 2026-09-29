import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/buildings';
import { downloadWithProgress, readTotal, type FetchProgress } from 'src/lib/utils/fetchProgress';

/**
 * Chunked, resumable downloads on top of the backend's range-capable
 * FileResponse: chunks stream into an Origin Private File System part file
 * while IndexedDB keeps the resume state, so a pause, a network drop, or a
 * page reload continues from the last committed block boundary.
 */
interface DownloadRecord {
    url: string;
    etag: string;
    total: number; // bytes, 0 when unknown
    offset: number; // bytes committed to the part file
}

export interface ResumableDownloadOptions {
    onProgress?: (progress: FetchProgress) => void;
    signal?: AbortSignal;
}

const DB_NAME = 'hud-downloads';
const DB_VERSION = 1;
const STORE_NAME = 'downloads';
const PART_DIRECTORY = 'downloads';
const PART_SUFFIX = '.part';
// Commit cadence: the bytes of one unfinished block are the most a pause or a
// drop loses. One commit per block keeps the OPFS metadata cost negligible.
const COMMIT_BLOCK_BYTES = 8 * 1024 * 1024;

function resumableDownloadsSupported(): boolean {
    return (
        typeof navigator !== 'undefined' &&
        navigator.storage?.getDirectory !== undefined &&
        typeof indexedDB !== 'undefined' &&
        crypto?.subtle?.digest !== undefined
    );
}

// --- IndexedDB resume state -------------------------------------------------

function openDownloadDatabase(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
            if (!request.result.objectStoreNames.contains(STORE_NAME)) {
                request.result.createObjectStore(STORE_NAME);
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed'));
    });
}

async function withDownloadStore<T>(
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
    const db = await openDownloadDatabase();
    try {
        return await new Promise<T>((resolve, reject) => {
            const transaction = db.transaction(STORE_NAME, mode);
            const request = run(transaction.objectStore(STORE_NAME));
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
        });
    } finally {
        db.close();
    }
}

function getDownloadRecord(url: string): Promise<DownloadRecord | undefined> {
    return withDownloadStore<DownloadRecord | undefined>('readonly', (store) => store.get(url));
}

function putDownloadRecord(record: DownloadRecord): Promise<IDBValidKey> {
    return withDownloadStore('readwrite', (store) => store.put(record, record.url));
}

function deleteDownloadRecord(url: string): Promise<undefined> {
    return withDownloadStore<undefined>('readwrite', (store) => store.delete(url));
}

function listDownloadRecords(): Promise<DownloadRecord[]> {
    return withDownloadStore<DownloadRecord[]>('readonly', (store) => store.getAll());
}

// --- OPFS part files --------------------------------------------------------

async function hashUrl(url: string): Promise<string> {
    // Part file names are recomputed from the URL on every resume and app
    // start, so they must stay deterministic; SHA-256 keeps colliding URLs
    // from sharing one .part file.
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join(
        '',
    );
}

async function getPartDirectory(): Promise<FileSystemDirectoryHandle> {
    const root = await navigator.storage.getDirectory();
    return root.getDirectoryHandle(PART_DIRECTORY, { create: true });
}

async function truncatePartFile(handle: FileSystemFileHandle): Promise<void> {
    const writable = await handle.createWritable({ keepExistingData: true });
    try {
        await writable.truncate(0);
    } finally {
        await writable.close();
    }
}

function readRangeTotal(response: Response): number {
    // "Content-Range: bytes 0-99/1234" on a 206 response carries the full size.
    const raw = response.headers.get('content-range');
    const match = raw?.match(/\/(\d+)$/);
    const total = match ? Number(match[1]) : 0;
    return Number.isFinite(total) && total > 0 ? total : 0;
}

function fetchWithResumeHeaders(
    url: string,
    init: RequestInit,
    offset: number,
    etag: string,
): Promise<Response> {
    const headers = new Headers(init.headers);
    if (offset > 0 && etag) {
        headers.set('Range', `bytes=${offset}-`);
        headers.set('If-Range', etag);
    }
    return authFetch(url, { ...init, headers });
}

async function downloadWhole(
    url: string,
    init: RequestInit,
    opts: ResumableDownloadOptions,
): Promise<Blob> {
    // Browsers without OPFS/IndexedDB keep the previous behavior: stream the
    // whole body (with progress) and hold it in memory.
    const buffer = await downloadWithProgress(url, init, opts.onProgress);
    return new Blob([buffer]);
}

async function finalizeDownload(
    directory: FileSystemDirectoryHandle,
    partName: string,
    url: string,
    partHandle: FileSystemFileHandle,
): Promise<Blob> {
    // Read every byte while the part file still exists: reads from a File
    // whose OPFS entry was removed hang or fail, which broke every download.
    const buffer = await (await partHandle.getFile()).arrayBuffer();
    await clearDownload(directory, partName, url);
    return new Blob([buffer]);
}

async function clearDownload(
    directory: FileSystemDirectoryHandle,
    partName: string,
    url: string,
): Promise<void> {
    await deleteDownloadRecord(url).catch(() => undefined);
    await directory.removeEntry(partName).catch(() => undefined);
}

export async function downloadResumable(
    url: string | URL,
    init: RequestInit,
    opts: ResumableDownloadOptions = {},
): Promise<Blob> {
    const urlText = String(url);
    if (!resumableDownloadsSupported()) {
        return downloadWhole(urlText, init, opts);
    }

    const directory = await getPartDirectory();
    const partName = `${await hashUrl(urlText)}${PART_SUFFIX}`;
    const partHandle = await directory.getFileHandle(partName, { create: true });

    const freshRecord = (): DownloadRecord => ({
        url: urlText,
        etag: '',
        total: 0,
        offset: 0,
    });

    // Resolve the stored record against the part file that actually exists: a
    // crash between a record update and a commit must never be trusted.
    const stored = await getDownloadRecord(urlText);
    let record = freshRecord();
    if (stored) {
        const size = (await partHandle.getFile()).size;
        if (size === 0 && stored.offset > 0) {
            record = freshRecord(); // the part file vanished or was emptied
        } else {
            record = { ...stored, offset: Math.min(stored.offset, size) };
        }
    }

    // A crash between a part-file commit and its record update leaves a
    // non-empty part file behind a zero offset; that tail is stale.
    if (record.offset === 0 && (await partHandle.getFile()).size > 0) {
        await truncatePartFile(partHandle);
    }

    // The stored offset already covers the whole known file size.
    if (record.total > 0 && record.offset >= record.total) {
        return finalizeDownload(directory, partName, urlText, partHandle);
    }

    let offset = record.offset;
    let response = await fetchWithResumeHeaders(urlText, init, offset, record.etag);

    if (response.status === 416) {
        // The file shrank below the stored offset; restart from zero.
        offset = 0;
        await truncatePartFile(partHandle);
        record = freshRecord();
        response = await fetchWithResumeHeaders(urlText, init, 0, '');
    }

    if (response.status === 200 && offset > 0) {
        // A full 200 on a resumed request means the If-Range validator did not
        // match: the file changed, so the stored bytes are stale.
        offset = 0;
        await truncatePartFile(partHandle);
        record = freshRecord();
    }

    if (!response.ok) {
        throw new ApiError(`Request failed with HTTP ${response.status}`, response.status, null);
    }

    const etag = response.headers.get('etag') ?? '';
    const total = response.status === 206 ? readRangeTotal(response) : readTotal(response);
    if (offset === 0) {
        record = { ...record, etag, total };
        await putDownloadRecord(record);
    }

    if (response.body === null) {
        const blob = await response.blob();
        await clearDownload(directory, partName, urlText);
        return blob;
    }

    const block = new Uint8Array(COMMIT_BLOCK_BYTES);
    let blockSize = 0;

    const commitBlock = async (): Promise<void> => {
        if (blockSize === 0) return;
        const writable = await partHandle.createWritable({ keepExistingData: true });
        try {
            await writable.write({
                type: 'write',
                position: offset,
                data: block.subarray(0, blockSize),
            });
            await writable.close();
        } catch (error) {
            // An interrupted commit leaves the previous state on disk; the
            // record keeps the last committed block boundary.
            await writable.abort().catch(() => undefined);
            throw error;
        }
        offset += blockSize;
        blockSize = 0;
        record = { ...record, offset, total: total || record.total, etag: etag || record.etag };
        await putDownloadRecord(record);
        opts.onProgress?.({ loaded: offset, total: total || record.total });
    };

    const reader = response.body.getReader();
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        let chunkOffset = 0;
        while (chunkOffset < value.byteLength) {
            const take = Math.min(COMMIT_BLOCK_BYTES - blockSize, value.byteLength - chunkOffset);
            block.set(value.subarray(chunkOffset, chunkOffset + take), blockSize);
            blockSize += take;
            chunkOffset += take;
        }
        // Report per network chunk too, so files smaller than one commit
        // block still move the progress bar.
        opts.onProgress?.({ loaded: offset + blockSize, total: total || record.total });
        if (blockSize === COMMIT_BLOCK_BYTES) {
            await commitBlock();
        }
    }
    await commitBlock();

    if (response.status === 200 || (total > 0 && offset >= total)) {
        return finalizeDownload(directory, partName, urlText, partHandle);
    }
    // The stream ended before the full size arrived; the record keeps the
    // offset, so the next attempt resumes from there.
    throw new ApiError(`Incomplete download: ${offset} of ${total} bytes`, 0, null);
}

/**
 * Remove part files with no matching record and zero the offset of records
 * whose part file disappeared. Call once at app start.
 */
export async function cleanupStaleDownloads(): Promise<void> {
    if (!resumableDownloadsSupported()) return;
    const directory = await getPartDirectory();
    const partNames = new Set<string>();
    for await (const name of directory.keys()) {
        if (name.endsWith(PART_SUFFIX)) partNames.add(name);
    }
    for (const record of await listDownloadRecords()) {
        const partName = `${await hashUrl(record.url)}${PART_SUFFIX}`;
        if (!partNames.has(partName)) {
            // The part file disappeared; a new attempt must start from zero.
            await putDownloadRecord({ ...record, offset: 0 });
        } else {
            partNames.delete(partName);
        }
    }
    // Part files without a record can never be resumed.
    for (const name of partNames) {
        await directory.removeEntry(name).catch(() => undefined);
    }
}
