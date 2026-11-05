import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/api';
import { parseContentRange } from 'src/lib/utils/contentRange';
import type { DownloadFile } from './downloadFile';
import { DiskDownloadFile } from './diskDownloadFile';
import { MemoryDownloadFile } from './memoryDownloadFile';
import { DownloadsDatabase } from './downloadsDatabase';
import { readResponseChunks, waitForNetwork, withAbortController } from 'src/lib/utils/network';
import type { DownloadMetadata, DownloadOptions } from './types';

const activeMemoryDownloads = new Set<string>();

export class ResumableDownload {
    private metadataValue: DownloadMetadata | null = null;
    private running = false;

    private constructor(
        readonly url: string,
        private file: DownloadFile,
        private readonly database: DownloadsDatabase | null,
    ) {}

    static async open(url: string | URL): Promise<ResumableDownload> {
        const persistent = isPersistentStorageAvailable();
        const urlText = String(url);

        return withDownloadLock(urlText, persistent, async () => {
            const file = persistent
                ? await DiskDownloadFile.open(urlText)
                : new MemoryDownloadFile();

            const database = persistent ? new DownloadsDatabase() : null;
            const download = new ResumableDownload(urlText, file, database);
            await download.restoreCheckpoint();

            return download;
        });
    }

    get downloadedBytes(): number {
        return this.file.size;
    }

    get metadata(): DownloadMetadata | null {
        return this.metadataValue ? { ...this.metadataValue } : null;
    }

    async download(options: DownloadOptions = {}): Promise<Blob> {
        return this.exclusively(() =>
            withAbortController(options.signal, async (controller) => {
                // Another instance or tab may have advanced or reset this file.
                if (this.database) this.file = await DiskDownloadFile.open(this.url);
                await this.restoreCheckpoint();
                controller.signal.throwIfAborted();

                const reportProgress = () => {
                    if (!controller.signal.aborted) {
                        options.onProgress?.({
                            loaded: this.file.size,
                            total: this.metadataValue?.totalBytes ?? 0,
                        });
                    }
                };
                reportProgress();

                if (!this.metadataValue?.complete) {
                    await this.transfer(controller, reportProgress);
                    await this.finish(controller.signal);
                }
                controller.signal.throwIfAborted();
                reportProgress();
                return this.file.toBlob();
            }),
        );
    }

    private async transfer(controller: AbortController, reportProgress: () => void): Promise<void> {
        const response = await this.requestRemaining(controller);
        try {
            await this.acceptResponse(response);
            reportProgress();
            await this.receive(response, controller, reportProgress);
        } finally {
            void response.body?.cancel().catch(() => undefined);
        }
    }

    private async finish(signal: AbortSignal): Promise<void> {
        await this.file.flush();
        signal.throwIfAborted();

        const metadata = this.metadataValue;
        if (!metadata) throw new Error('Missing download metadata.');

        if (metadata.totalBytes !== null && this.file.size !== metadata.totalBytes) {
            throw new Error(
                `Incomplete download: ${this.file.size} of ${metadata.totalBytes} bytes.`,
            );
        }

        const completed: DownloadMetadata = {
            ...metadata,
            totalBytes: metadata.totalBytes ?? this.file.size,
            complete: true,
        };

        await this.saveCheckpoint(this.file.committedBytes, completed);
        this.metadataValue = completed;
    }

    async reset(): Promise<void> {
        await this.exclusively(async () => {
            if (this.database) this.file = await DiskDownloadFile.open(this.url);
            await this.discardContent();
        });
    }

    private async exclusively<T>(operation: () => Promise<T>): Promise<T> {
        if (this.running) throw new Error('This download is already running.');
        this.running = true;
        try {
            return await withDownloadLock(this.url, this.database !== null, operation);
        } finally {
            this.running = false;
        }
    }

    private async restoreCheckpoint(): Promise<void> {
        if (!this.database) return;
        const record = await this.database.get(this.url);
        const offset = Math.min(record?.committedBytes ?? 0, this.file.size);
        if (this.file.size !== offset) await this.file.truncate(offset);
        this.metadataValue = record
            ? {
                  etag: record.etag,
                  totalBytes: record.totalBytes,
                  complete: record.complete && offset === record.totalBytes,
              }
            : null;
        this.file.onCommit = (committedBytes) => this.saveCheckpoint(committedBytes);
        if (
            record &&
            (offset !== record.committedBytes || record.complete !== this.metadataValue?.complete)
        ) {
            await this.saveCheckpoint(offset);
        }
    }

    private async saveCheckpoint(
        committedBytes: number,
        metadata: DownloadMetadata | null = this.metadataValue,
    ): Promise<void> {
        if (!metadata) throw new Error('Cannot checkpoint without response metadata.');
        await this.database?.save({ url: this.url, committedBytes, ...metadata });
    }

    private async discardContent(): Promise<void> {
        // Invalidate metadata first: a crash must not associate old metadata with new bytes.
        await this.database?.delete(this.url);
        this.metadataValue = null;
        await this.file.remove();
        this.file.onCommit = (committedBytes) => this.saveCheckpoint(committedBytes);
    }

    private async requestRemaining(controller: AbortController): Promise<Response> {
        if (this.file.size > 0 && !hasStrongEtag(this.metadataValue?.etag)) {
            await this.discardContent();
        }
        let response = await this.fetch(controller);
        if (response.status === 416) {
            void response.body?.cancel().catch(() => undefined);
            await this.discardContent();
            response = await this.fetch(controller);
        }
        if (!response.ok) {
            void response.body?.cancel().catch(() => undefined);
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
        if (this.file.size > 0 && hasStrongEtag(etag)) {
            headers.set('Range', `bytes=${this.file.size}-`);
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
            // 200 means that we got the full file in one go, so we can safely discard any previous content
            if (this.file.size > 0) await this.discardContent();
            this.metadataValue = { etag, totalBytes: readTotalBytes(response), complete: false };
        } else if (response.status === 206) {
            // 206 means that we got a partial file, so we need to make a real resumable download
            const { start, end, total } = parseContentRange(response.headers.get('content-range'));
            if (start !== this.file.size || end !== total - 1) {
                throw new Error('The response does not match the requested range.');
            }
            const previous = this.metadataValue;
            if (previous?.etag && etag && previous.etag !== etag) {
                throw new Error('The remote file changed during the download.');
            }
            if (previous?.totalBytes != null && previous.totalBytes !== total) {
                throw new Error('The remote file size changed during the download.');
            }
            this.metadataValue = {
                etag: etag ?? previous?.etag ?? null,
                totalBytes: total,
                complete: false,
            };
        } else {
            throw new Error(`Unexpected download response: HTTP ${response.status}.`);
        }
    }

    private async receive(
        response: Response,
        controller: AbortController,
        reportProgress: () => void,
    ): Promise<void> {
        let storageFailed = false;
        try {
            for await (const chunk of readResponseChunks(response, controller)) {
                controller.signal.throwIfAborted();
                const total = this.metadataValue?.totalBytes;
                if (total != null && chunk.byteLength > total - this.file.size) {
                    throw new Error('Download response exceeds the expected file size.');
                }
                try {
                    await this.file.append(chunk);
                } catch (error) {
                    storageFailed = true;
                    throw error;
                }
                controller.signal.throwIfAborted();
                reportProgress();
            }
        } catch (error) {
            if (storageFailed) throw error;
            try {
                // Persistence is deliberately independent of the aborted network signal.
                await this.file.flush();
            } catch (saveError) {
                throw new AggregateError(
                    [error, saveError],
                    'Download failed and its final checkpoint could not be saved.',
                );
            }
            throw error;
        }
    }
}

async function withDownloadLock<T>(
    url: string,
    persistent: boolean,
    operation: () => Promise<T>,
): Promise<T> {
    if (persistent) {
        return navigator.locks.request(
            `hud-resumable-download:${url}`,
            { ifAvailable: true },
            (lock) => {
                if (!lock) throw new Error('This URL is already being downloaded.');
                return operation();
            },
        );
    }
    if (activeMemoryDownloads.has(url)) {
        throw new Error('This URL is already being downloaded.');
    }
    activeMemoryDownloads.add(url);
    try {
        return await operation();
    } finally {
        activeMemoryDownloads.delete(url);
    }
}

function hasStrongEtag(etag: string | null | undefined): etag is string {
    return typeof etag === 'string' && /^"[^"]*"$/.test(etag);
}

function readTotalBytes(response: Response): number | null {
    const encoding = response.headers.get('content-encoding');
    const length =
        encoding && encoding !== 'identity' ? null : response.headers.get('content-length');
    const raw = response.headers.get('x-file-size') ?? length;
    if (raw === null || raw.trim() === '') return null;
    const total = Number(raw);
    return Number.isSafeInteger(total) && total >= 0 ? total : null;
}

function isPersistentStorageAvailable(): boolean {
    return (
        DiskDownloadFile.isAvailable() &&
        DownloadsDatabase.isAvailable() &&
        typeof navigator.locks?.request === 'function'
    );
}
