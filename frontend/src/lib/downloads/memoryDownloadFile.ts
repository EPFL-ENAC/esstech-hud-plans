import { assertTruncation, type DownloadFile } from './downloadFile';

export class MemoryDownloadFile implements DownloadFile {
    private chunks: Blob[] = [];
    private byteLength = 0;

    get size(): number {
        return this.byteLength;
    }

    append(bytes: Uint8Array<ArrayBuffer>): Promise<void> {
        // Blob snapshots the bytes before the caller reuses its buffer.
        this.chunks.push(new Blob([bytes]));
        this.byteLength += bytes.byteLength;
        return Promise.resolve();
    }

    truncate(size: number): Promise<void> {
        assertTruncation(size, this.byteLength);
        this.chunks = size === 0 ? [] : [new Blob(this.chunks).slice(0, size)];
        this.byteLength = size;
        return Promise.resolve();
    }

    toBlob(): Promise<Blob> {
        return Promise.resolve(new Blob(this.chunks));
    }

    remove(): Promise<void> {
        return this.truncate(0);
    }
}
