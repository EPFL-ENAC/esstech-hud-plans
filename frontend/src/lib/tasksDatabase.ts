import type { SerializedTask, TaskFiles, TaskSnapshot } from 'src/lib/networkDependentTasks';
import type { StoredTaskSnapshot } from 'src/lib/taskRegistry';

export class TasksDatabase {
    private pending: Promise<void> = Promise.resolve();
    private closed = false;

    create({ snapshot, files = {} }: SerializedTask): Promise<void> {
        return this.enqueue(() =>
            this.transaction('readwrite', (transaction) => {
                transaction.objectStore('tasks').add(snapshot);
                const store = transaction.objectStore('files');
                for (const [name, file] of Object.entries(files)) {
                    store.add(file, [snapshot.ownerId, snapshot.id, name]);
                }
            }),
        );
    }

    save(snapshot: TaskSnapshot): Promise<void> {
        return this.enqueue(() =>
            this.transaction('readwrite', (transaction) => {
                const store = transaction.objectStore('tasks');
                const request = store.get([snapshot.ownerId, snapshot.id]);
                request.onsuccess = () => {
                    // A late checkpoint must never recreate a deleted task.
                    if (request.result !== undefined) store.put(snapshot);
                };
            }),
        );
    }

    async list(ownerId: string): Promise<StoredTaskSnapshot[]> {
        let request: IDBRequest<StoredTaskSnapshot[]>;
        await this.enqueue(() =>
            this.transaction('readonly', (transaction) => {
                request = transaction.objectStore('tasks').index('ownerId').getAll(ownerId);
            }),
        );
        return request!.result;
    }

    files(ownerId: string, taskId: string): TaskFiles {
        return {
            get: async (name) => {
                let request: IDBRequest<File | undefined>;
                await this.enqueue(() =>
                    this.transaction('readonly', (transaction) => {
                        request = transaction.objectStore('files').get([ownerId, taskId, name]);
                    }),
                );
                const file = request!.result;
                if (file === undefined) throw new Error('Saved task file is missing.');
                return file;
            },
        };
    }

    delete(ownerId: string, taskId: string): Promise<void> {
        return this.enqueue(() =>
            this.transaction('readwrite', (transaction) => {
                transaction.objectStore('tasks').delete([ownerId, taskId]);
                const store = transaction.objectStore('files');
                const request = store.openKeyCursor(
                    IDBKeyRange.bound([ownerId, taskId], [ownerId, taskId, []]),
                );
                request.onsuccess = () => {
                    const cursor = request.result;
                    if (!cursor) return;
                    store.delete(cursor.primaryKey);
                    cursor.continue();
                };
            }),
        );
    }

    clear(): Promise<void> {
        return this.enqueue(() => this.clearRecords());
    }

    async clearAndClose(): Promise<void> {
        this.closed = true;
        await this.pending.catch(() => undefined);
        await this.clearRecords();
    }

    private clearRecords(): Promise<void> {
        return this.transaction('readwrite', (transaction) => {
            transaction.objectStore('tasks').clear();
            transaction.objectStore('files').clear();
        });
    }

    private enqueue(operation: () => Promise<void>): Promise<void> {
        if (this.closed) return Promise.reject(new Error('Task storage is closed.'));
        const result = this.pending.catch(() => undefined).then(operation);
        this.pending = result;
        return result;
    }

    private open(): Promise<IDBDatabase> {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('hud-network-tasks', 1);
            let blocked = false;
            request.onupgradeneeded = () => {
                const database = request.result;
                const tasks = database.createObjectStore('tasks', { keyPath: ['ownerId', 'id'] });
                tasks.createIndex('ownerId', 'ownerId');
                database.createObjectStore('files');
            };
            request.onsuccess = () => {
                if (blocked) request.result.close();
                else resolve(request.result);
            };
            request.onerror = () =>
                reject(request.error ?? new Error('Could not open task storage.'));
            request.onblocked = () => {
                blocked = true;
                reject(new Error('Task storage is blocked by another window.'));
            };
        });
    }

    private async transaction(
        mode: IDBTransactionMode,
        operation: (transaction: IDBTransaction) => void,
    ): Promise<void> {
        const database = await this.open();
        try {
            await new Promise<void>((resolve, reject) => {
                const transaction = database.transaction(['tasks', 'files'], mode);
                transaction.oncomplete = () => resolve();
                transaction.onabort = () =>
                    reject(transaction.error ?? new Error('Task storage transaction failed.'));
                try {
                    operation(transaction);
                } catch (error) {
                    transaction.abort();
                    reject(
                        error instanceof Error
                            ? error
                            : new Error('Task storage failed.', { cause: error }),
                    );
                }
            });
        } finally {
            database.close();
        }
    }
}
