import type { FetchProgress } from 'src/lib/utils/fetchProgress';

export interface DownloadOptions {
    signal?: AbortSignal;
    onProgress?: (progress: FetchProgress) => void;
}

export interface DownloadMetadata {
    totalBytes: number | null;
    etag: string | null;
}

/** A checkpoint contains only bytes already committed to the file. */
export interface DownloadRecord {
    url: string;
    offset: number;
    total: number;
    etag: string;
}
