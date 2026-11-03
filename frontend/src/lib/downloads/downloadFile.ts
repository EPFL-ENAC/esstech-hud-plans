export interface DownloadFile {
    readonly size: number;

    append(bytes: Uint8Array<ArrayBuffer>): Promise<void>;
    truncate(size: number): Promise<void>;
    toBlob(): Promise<Blob>;
    remove(): Promise<void>;
}

export function assertTruncation(size: number, currentSize: number): void {
    if (!Number.isSafeInteger(size) || size < 0 || size > currentSize) {
        throw new RangeError(`Cannot truncate ${currentSize} bytes to ${size}.`);
    }
}
