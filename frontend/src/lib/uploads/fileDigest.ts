/** A guard value that detects a re-selected file before a chunked resume. */
export interface FileFingerprint {
    name: string;
    size: number;
    lastModified: number;
}

/** One planned chunk of an upload, as the POST /uploads chunks entry. */
export interface ChunkPlanEntry {
    index: number;
    // Byte offset inside the file. The server derives it from the index.
    offset: number;
    size: number;
    sha256: string;
}

/** Build the identity fingerprint of a picked file. */
export function makeFileFingerprint(file: File): FileFingerprint {
    return { name: file.name, size: file.size, lastModified: file.lastModified };
}

/**
 * Compare a stored fingerprint against the file at resume time. Any changed
 * field means the user re-selected the file, so the session must restart.
 */
export function fingerprintMatches(file: File, fingerprint: FileFingerprint): boolean {
    return (
        file.name === fingerprint.name &&
        file.size === fingerprint.size &&
        file.lastModified === fingerprint.lastModified
    );
}

export function chunkCountForSize(totalSize: number, chunkSize: number): number {
    if (totalSize <= 0) return 0;
    if (chunkSize <= 0) throw new Error('chunk size must be positive');
    return Math.ceil(totalSize / chunkSize);
}

/** Byte size of one planned chunk. The last partial chunk is smaller. */
export function chunkSizeForIndex(index: number, totalSize: number, chunkSize: number): number {
    const offset = index * chunkSize;
    return Math.min(chunkSize, totalSize - offset);
}

export async function digestBytes(bytes: ArrayBuffer): Promise<string> {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Slice one planned chunk of the file and compute its SHA-256 digest. */
export async function digestFileChunk(
    file: File,
    index: number,
    chunkSize: number,
): Promise<string> {
    const offset = index * chunkSize;
    const size = chunkSizeForIndex(index, file.size, chunkSize);
    const slice = file.slice(offset, offset + size);
    return digestBytes(await slice.arrayBuffer());
}

/**
 * Build the full chunk plan of a file. Reading the file in sequential slices
 * keeps memory at one chunk, and each digest lets the backend verify a PUT.
 */
export async function buildChunkPlan(file: File, chunkSize: number): Promise<ChunkPlanEntry[]> {
    const count = chunkCountForSize(file.size, chunkSize);
    const plan: ChunkPlanEntry[] = [];
    for (let index = 0; index < count; index++) {
        const sha256 = await digestFileChunk(file, index, chunkSize);
        plan.push({
            index,
            offset: index * chunkSize,
            size: chunkSizeForIndex(index, file.size, chunkSize),
            sha256,
        });
    }
    return plan;
}
