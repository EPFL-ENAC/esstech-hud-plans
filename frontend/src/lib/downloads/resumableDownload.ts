import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/api';
import { readResponseChunks, waitForNetwork, withAbortController } from 'src/lib/utils/network';
import { cleanupStaleDownloads } from './cleanupStaleDownloads';
import type { DownloadFile } from './downloadFile';
import { DiskDownloadFile } from './diskDownloadFile';
import { MemoryDownloadFile } from './memoryDownloadFile';
import { DownloadsDatabase } from './downloadsDatabase';
import type { DownloadMetadata, DownloadOptions } from './types';

const COMMIT_BLOCK_BYTES = 8 * 1024 * 1024;

export class ResumableDownload {
    private metadataValue: DownloadMetadata | null = null;
    private readonly buffer = new Uint8Array(COMMIT_BLOCK_BYTES);
    private bufferedBytes = 0;
    private result: Blob | null = null;
    private running = false;

    private constructor(
        readonly url: string,
        private readonly downloadFile: DownloadFile,
        private readonly database: DownloadsDatabase | null,
    ) {}

    static async open(url: string | URL): Promise<ResumableDownload> {
        await cleanupStaleDownloads().catch(() => undefined);
        const urlText = String(url);
        const persistent = DiskDownloadFile.isStorageAvailable() && DownloadsDatabase.isAvailable();
        const file = persistent
            ? await DiskDownloadFile.hashUrlAndOpen(urlText)
            : new MemoryDownloadFile();
        const database = persistent ? new DownloadsDatabase() : null;
        const download = new ResumableDownload(urlText, file, database);
        await download.restoreCheckpoint();
        return download;
    }

    /** Includes buffered bytes retained by this instance between attempts. */
    get downloadedBytes(): number {
        return this.result?.size ?? this.downloadFile.size + this.bufferedBytes;
    }

    get metadata(): DownloadMetadata | null {
        return this.metadataValue ? { ...this.metadataValue } : null;
    }

    async download(options: DownloadOptions = {}): Promise<Blob> {
        if (this.running) throw new Error('This download is already running.');
        this.running = true;
        try {
            return await withAbortController(options.signal, async (controller) => {
                const reportProgress = () => {
                    if (!controller.signal.aborted) {
                        options.onProgress?.({
                            loaded: this.downloadedBytes,
                            total: this.metadataValue?.totalBytes ?? 0,
                        });
                    }
                };
                if (this.result) {
                    reportProgress();
                    return this.result;
                }

                await this.flush();
                await this.saveCheckpoint();
                reportProgress();

                if (!this.isComplete()) {
                    const response = await this.requestRemaining(controller);
                    await this.acceptResponse(response);
                    reportProgress();
                    for await (const chunk of readResponseChunks(response, controller)) {
                        await this.append(chunk);
                        reportProgress();
                    }
                    await this.flush();
                    this.assertComplete();

                    const metadata = this.metadataValue;
                    if (metadata && metadata.totalBytes === null) {
                        this.metadataValue = { ...metadata, totalBytes: this.downloadedBytes };
                        await this.saveCheckpoint();
                    }
                }

                reportProgress();
                const blob = await this.downloadFile.toBlob();
                this.result = blob;
                await this.removeSavedData();
                return blob;
            });
        } finally {
            this.running = false;
        }
    }

    async reset(): Promise<void> {
        if (this.running) throw new Error('Cancel the active download before resetting it.');
        await this.resetContent();
    }

    private async restoreCheckpoint(): Promise<void> {
        const record = await this.database?.get(this.url);
        const offset = Math.min(record?.offset ?? 0, this.downloadFile.size);
        if (this.downloadFile.size !== offset) await this.downloadFile.truncate(offset);
        this.metadataValue = record
            ? { totalBytes: record.total > 0 ? record.total : null, etag: record.etag || null }
            : null;
        await this.saveCheckpoint();
    }

    private async saveCheckpoint(): Promise<void> {
        await this.database?.save({
            url: this.url,
            offset: this.downloadFile.size,
            total: this.metadataValue?.totalBytes ?? 0,
            etag: this.metadataValue?.etag ?? '',
        });
    }

    private async requestRemaining(controller: AbortController): Promise<Response> {
        if (this.downloadedBytes > 0 && !this.metadataValue?.etag) await this.resetContent();
        let response = await this.fetch(controller);
        if (response.status === 416) {
            void response.body?.cancel().catch(() => undefined);
            await this.resetContent();
            response = await this.fetch(controller);
        }
        if (!response.ok) {
            throw new ApiError(
                `Request failed with HTTP ${response.status}`,
                response.status,
                null,
            );
        }
        return response;
    }

    private fetch(controller: AbortController): Promise<Response> {
        const headers = new Headers();
        const etag = this.metadataValue?.etag;
        if (this.downloadedBytes > 0 && etag) {
            headers.set('Range', `bytes=${this.downloadedBytes}-`);
            headers.set('If-Range', etag);
        }
        return waitForNetwork(
            () => authFetch(this.url, { headers, signal: controller.signal }),
            controller,
        );
    }

    private async acceptResponse(response: Response): Promise<void> {
        const etag = response.headers.get('etag');
        if (response.status === 200) {
            if (this.downloadedBytes > 0) await this.resetContent();
            this.metadataValue = { totalBytes: readTotalBytes(response), etag };
        } else if (response.status === 206) {
            const match = response.headers
                .get('content-range')
                ?.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
            if (!match) throw new Error('Invalid Content-Range in download response.');
            const start = Number(match[1]);
            const end = Number(match[2]);
            const total = Number(match[3]);
            if (
                ![start, end, total].every(Number.isSafeInteger) ||
                start !== this.downloadedBytes ||
                end < start ||
                total <= end
            ) {
                throw new Error('The response does not match the saved offset.');
            }
            const previous = this.metadataValue;
            if (previous?.etag && etag && previous.etag !== etag) {
                throw new Error('The remote file changed during the download.');
            }
            const previousTotal = previous?.totalBytes ?? null;
            if (previousTotal !== null && previousTotal !== total) {
                throw new Error('The remote file size changed during the download.');
            }
            this.metadataValue = { totalBytes: total, etag: etag ?? previous?.etag ?? null };
        } else {
            throw new Error(`Unexpected download response: HTTP ${response.status}.`);
        }
        await this.saveCheckpoint();
    }

    private async append(chunk: Uint8Array): Promise<void> {
        let offset = 0;
        while (offset < chunk.byteLength) {
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

    private async flush(): Promise<void> {
        if (this.bufferedBytes === 0) return;
        await this.downloadFile.append(this.buffer.subarray(0, this.bufferedBytes));
        this.bufferedBytes = 0;
        // A durable file write must precede its database checkpoint.
        await this.saveCheckpoint();
    }

    private async resetContent(): Promise<void> {
        await this.downloadFile.truncate(0);
        this.bufferedBytes = 0;
        this.metadataValue = null;
        this.result = null;
        await this.saveCheckpoint();
    }

    private isComplete(): boolean {
        const total = this.metadataValue?.totalBytes ?? null;
        return total !== null && this.downloadedBytes === total;
    }

    private assertComplete(): void {
        const total = this.metadataValue?.totalBytes ?? null;
        if (total !== null && this.downloadedBytes !== total) {
            throw new Error(`Incomplete download: ${this.downloadedBytes} of ${total} bytes.`);
        }
    }

    private async removeSavedData(): Promise<void> {
        await this.database?.delete(this.url).catch(() => undefined);
        await this.downloadFile.remove().catch(() => undefined);
    }
}

function readTotalBytes(response: Response): number | null {
    const encoding = response.headers.get('content-encoding');
    const contentLength =
        encoding && encoding !== 'identity' ? null : response.headers.get('content-length');
    const raw = response.headers.get('x-file-size') ?? contentLength;
    if (raw === null || raw.trim() === '') return null;
    const total = Number(raw);
    return Number.isSafeInteger(total) && total >= 0 ? total : null;
}
