import { ApiError } from 'src/lib/api';

export interface RemoteUpload {
    uploadId: string;
    uploadUrl: string;
}

export interface LocalUploadRecord {
    id: string;
    ownerId: string;
    createdAt: number;
    file: {
        name: string;
        type: string;
        size: number;
        lastModified: number;
    };
    remote: RemoteUpload | null;
}

export class LocalUploadStorageError extends Error {
    constructor(cause: unknown) {
        super('Could not access uploads saved on this device.', { cause });
    }
}

export class LocalUploadsRegistry {
    async create(ownerId: string, file: File): Promise<LocalUploadRecord> {
        if (file.size <= 0) {
            throw new ApiError('Upload file is empty', 400, null);
        }

        const record: LocalUploadRecord = {
            id: crypto.randomUUID(),
            ownerId,
            createdAt: Date.now(),
            file: {
                name: file.name,
                type: file.type,
                size: file.size,
                lastModified: file.lastModified,
            },
            remote: null,
        };

        await this.transaction(['uploads', 'files'], 'readwrite', (transaction) => {
            transaction.objectStore('uploads').add(record);
            transaction.objectStore('files').add(file, [ownerId, record.id]);
        });

        return record;
    }

    async get(ownerId: string, localUploadId: string): Promise<LocalUploadRecord> {
        let request: IDBRequest<LocalUploadRecord | undefined>;

        await this.transaction(['uploads'], 'readonly', (transaction) => {
            request = transaction.objectStore('uploads').get([ownerId, localUploadId]);
        });

        const record = request!.result;
        if (record === undefined) {
            throw new Error('Local upload is missing.');
        }

        return record;
    }

    async list(ownerId: string): Promise<LocalUploadRecord[]> {
        let request: IDBRequest<LocalUploadRecord[]>;

        await this.transaction(['uploads'], 'readonly', (transaction) => {
            request = transaction.objectStore('uploads').index('ownerId').getAll(ownerId);
        });

        return request!.result;
    }

    async getFile(ownerId: string, localUploadId: string): Promise<File> {
        let request: IDBRequest<File | undefined>;

        await this.transaction(['files'], 'readonly', (transaction) => {
            request = transaction.objectStore('files').get([ownerId, localUploadId]);
        });

        const file = request!.result;
        if (file === undefined) {
            throw new Error('Local upload file is missing.');
        }

        return file;
    }

    async setRemote(ownerId: string, localUploadId: string, remote: RemoteUpload): Promise<void> {
        await this.transaction(['uploads'], 'readwrite', (transaction, abort) => {
            const store = transaction.objectStore('uploads');
            const request: IDBRequest<LocalUploadRecord | undefined> = store.get([
                ownerId,
                localUploadId,
            ]);

            request.onsuccess = () => {
                try {
                    const record = request.result;
                    if (record === undefined) {
                        throw new Error('Local upload is missing.');
                    }

                    if (record.remote !== null) {
                        if (
                            record.remote.uploadId !== remote.uploadId ||
                            record.remote.uploadUrl !== remote.uploadUrl
                        ) {
                            throw new Error('Local upload already has a different remote upload.');
                        }

                        return;
                    }

                    store.put({
                        ...record,
                        remote: { ...remote },
                    } satisfies LocalUploadRecord);
                } catch (error) {
                    abort(error);
                }
            };
        });
    }

    private open(): Promise<IDBDatabase> {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('hud-local-uploads', 1);
            let blocked = false;

            request.onupgradeneeded = () => {
                const database = request.result;
                const uploads = database.createObjectStore('uploads', {
                    keyPath: ['ownerId', 'id'],
                });

                uploads.createIndex('ownerId', 'ownerId');
                database.createObjectStore('files');
            };

            request.onsuccess = () => {
                if (blocked) request.result.close();
                else resolve(request.result);
            };

            request.onerror = () => {
                reject(request.error ?? new Error('Could not open local upload storage.'));
            };

            request.onblocked = () => {
                blocked = true;
                reject(new Error('Local upload storage is blocked by another window.'));
            };
        });
    }

    private async transaction(
        stores: string[],
        mode: IDBTransactionMode,
        operation: (transaction: IDBTransaction, abort: (error: unknown) => void) => void,
    ): Promise<void> {
        try {
            const database = await this.open();

            try {
                await new Promise<void>((resolve, reject) => {
                    const transaction = database.transaction(stores, mode);
                    let failure: Error | null = null;

                    const abort = (error: unknown): void => {
                        failure =
                            error instanceof Error
                                ? error
                                : new Error('Local upload storage failed.', { cause: error });
                        transaction.abort();
                    };

                    transaction.oncomplete = () => resolve();
                    transaction.onabort = () => {
                        reject(
                            failure ??
                                transaction.error ??
                                new Error('Local upload storage transaction failed.'),
                        );
                    };

                    try {
                        operation(transaction, abort);
                    } catch (error) {
                        abort(error);
                    }
                });
            } finally {
                database.close();
            }
        } catch (error) {
            throw new LocalUploadStorageError(error);
        }
    }
}
