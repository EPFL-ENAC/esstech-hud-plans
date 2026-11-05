import { DownloadFile } from './downloadFile';

export class MemoryDownloadFile extends DownloadFile {
    private chunks: Blob[] = [];

    constructor() {
        super();
    }

    protected write(_offset: number, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
        this.chunks.push(new Blob([bytes]));
        return Promise.resolve();
    }

    protected truncateStorage(size: number): Promise<void> {
        this.chunks = size === 0 ? [] : [new Blob(this.chunks).slice(0, size)];
        return Promise.resolve();
    }

    protected readStorage(): Promise<Blob> {
        return Promise.resolve(new Blob(this.chunks));
    }

    protected removeStorage(): Promise<void> {
        this.chunks = [];
        return Promise.resolve();
    }
}
