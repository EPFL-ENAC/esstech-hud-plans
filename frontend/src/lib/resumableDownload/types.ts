export interface DownloadProgress {
    loaded: number;
    total: number;
}

export interface DownloadOptions {
    signal?: AbortSignal;
    onProgress?: (progress: DownloadProgress) => void;
}

export interface DownloadMetadata {
    etag: string | null;
    totalBytes: number | null;
    complete: boolean;
}

/** Contains only the prefix committed to storage, never the buffered tail. */
export interface DownloadRecord extends DownloadMetadata {
    url: string;
    committedBytes: number;
}
