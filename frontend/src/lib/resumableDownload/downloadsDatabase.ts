import type { DownloadRecord } from './types';

export class DownloadsDatabase {
    static isAvailable(): boolean {
        return typeof indexedDB !== 'undefined';
    }

    async get(url: string): Promise<DownloadRecord | null> {
        const record = await this.transaction<DownloadRecord | undefined>('readonly', (store) =>
            store.get(url),
        );
        return record ?? null;
    }

    async save(record: DownloadRecord): Promise<void> {
        await this.transaction('readwrite', (store) => store.put(record, record.url));
    }

    async delete(url: string): Promise<void> {
        await this.transaction('readwrite', (store) => store.delete(url));
    }

    private open(): Promise<IDBDatabase> {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('hud-resumable-downloads', 1);
            request.onupgradeneeded = () => request.result.createObjectStore('downloads');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => {
                reject(request.error ?? new Error('Could not open the downloads database.'));
            };
        });
    }

    private async transaction<T>(
        mode: IDBTransactionMode,
        operation: (store: IDBObjectStore) => IDBRequest<T>,
    ): Promise<T> {
        const database = await this.open();
        try {
            return await new Promise<T>((resolve, reject) => {
                const transaction = database.transaction('downloads', mode);
                const request = operation(transaction.objectStore('downloads'));
                // Request success alone does not mean a write was committed.
                transaction.oncomplete = () => resolve(request.result);
                transaction.onabort = () => {
                    reject(transaction.error ?? new Error('Download database transaction failed.'));
                };
            });
        } finally {
            database.close();
        }
    }
}
