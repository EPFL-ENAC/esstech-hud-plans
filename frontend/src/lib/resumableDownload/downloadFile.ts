export type CommitHandler = (committedBytes: number) => Promise<void>;

export const COMMIT_BLOCK_BYTES = 8 * 1024 * 1024;

/** Owns both the committed prefix and the buffered tail of a download. */
export abstract class DownloadFile {
    onCommit?: CommitHandler;

    private buffer: Uint8Array<ArrayBuffer> | null = null;
    private bufferedBytes = 0;
    private notificationPending = false;

    protected constructor(private storedBytes = 0) {}

    get size(): number {
        return this.storedBytes + this.bufferedBytes;
    }

    get committedBytes(): number {
        return this.storedBytes;
    }

    async append(chunk: Uint8Array): Promise<void> {
        await this.notifyCommit();
        this.buffer ??= new Uint8Array(COMMIT_BLOCK_BYTES);
        let offset = 0;
        while (offset < chunk.byteLength) {
            // A previous write failure may have left a full buffer to retry.
            if (this.bufferedBytes === COMMIT_BLOCK_BYTES) await this.flush();
            const count = Math.min(
                COMMIT_BLOCK_BYTES - this.bufferedBytes,
                chunk.byteLength - offset,
            );
            this.buffer.set(chunk.subarray(offset, offset + count), this.bufferedBytes);
            this.bufferedBytes += count;
            offset += count;
            if (this.bufferedBytes === COMMIT_BLOCK_BYTES) await this.flush();
        }
    }

    async flush(): Promise<void> {
        await this.notifyCommit();
        if (this.bufferedBytes === 0 || this.buffer === null) return;
        await this.write(this.storedBytes, this.buffer.subarray(0, this.bufferedBytes));
        this.storedBytes += this.bufferedBytes;
        this.bufferedBytes = 0;
        this.notificationPending = true;
        await this.notifyCommit();
    }

    /** Reconciliation only: the caller owns any corresponding metadata change. */
    async truncate(size: number): Promise<void> {
        if (!Number.isSafeInteger(size) || size < 0 || size > this.size) {
            throw new RangeError(`Cannot truncate ${this.size} bytes to ${size}.`);
        }
        if (size < this.storedBytes) {
            await this.truncateStorage(size);
            this.storedBytes = size;
            this.bufferedBytes = 0;
            this.notificationPending = false;
        } else {
            this.bufferedBytes = size - this.storedBytes;
        }
    }

    async toBlob(): Promise<Blob> {
        await this.flush();
        return this.readStorage();
    }

    async remove(): Promise<void> {
        await this.removeStorage();
        this.storedBytes = 0;
        this.bufferedBytes = 0;
        this.buffer = null;
        this.notificationPending = false;
    }

    private async notifyCommit(): Promise<void> {
        if (!this.notificationPending) return;
        await this.onCommit?.(this.storedBytes);
        this.notificationPending = false;
    }

    protected abstract write(offset: number, bytes: Uint8Array<ArrayBuffer>): Promise<void>;
    protected abstract truncateStorage(size: number): Promise<void>;
    protected abstract readStorage(): Promise<Blob>;
    protected abstract removeStorage(): Promise<void>;
}
