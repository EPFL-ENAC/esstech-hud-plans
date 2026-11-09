import type { BuildingSelection } from './buildings';
import {
    makeDefaultReconstructionSettings,
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
} from './reconstruction-settings';

export type CaptureDraftSource = { uploadId: string } | { video: Blob };

export interface CaptureDraftForm {
    buildingSelection: BuildingSelection;
    preset: ReconstructionPreset;
    advancedSettings: ReconstructionSettingsConfig;
}

export interface CaptureDraft {
    id: string;
    source: CaptureDraftSource;
    form: CaptureDraftForm;
}

interface DraftMetadata {
    source: { uploadId: string } | { localVideo: true };
    form: CaptureDraftForm;
}

export class CaptureDraftService {
    static readonly databaseName = 'hud-capture-drafts';

    async create({
        ownerId,
        source,
        buildingSelection,
    }: {
        ownerId: string;
        source: CaptureDraftSource;
        buildingSelection: BuildingSelection;
    }): Promise<string> {
        const id = crypto.randomUUID();
        const key = [ownerId, id];
        const metadata: DraftMetadata = {
            source: 'uploadId' in source ? source : { localVideo: true },
            form: {
                buildingSelection,
                preset: 'indoors',
                advancedSettings: makeDefaultReconstructionSettings('advanced'),
            },
        };

        await this.transact(['drafts', 'videos'], 'readwrite', (transaction) => {
            transaction.objectStore('drafts').add(metadata, key);
            if ('video' in source) transaction.objectStore('videos').add(source.video, key);
        });
        return id;
    }

    async get(id: string, { ownerId }: { ownerId: string }): Promise<CaptureDraft | null> {
        const key = [ownerId, id];
        const { metadataRequest, videoRequest } = await this.transact(
            ['drafts', 'videos'],
            'readonly',
            (transaction) => ({
                metadataRequest: transaction.objectStore('drafts').get(key),
                videoRequest: transaction.objectStore('videos').get(key),
            }),
        );
        const metadata = metadataRequest.result as DraftMetadata | undefined;
        if (!metadata) return null;

        const { source, form } = metadata;
        if ('uploadId' in source) return { id, source, form };

        const video = videoRequest.result as Blob | undefined;
        if (!video) throw new Error('Capture draft video is missing.');
        return { id, source: { video }, form };
    }

    async updateForm(
        id: string,
        { ownerId, form }: { ownerId: string; form: CaptureDraftForm },
    ): Promise<void> {
        await this.transact(['drafts'], 'readwrite', (transaction) => {
            const store = transaction.objectStore('drafts');
            const key = [ownerId, id];
            const request = store.get(key);
            request.onsuccess = () => {
                const metadata = request.result as DraftMetadata | undefined;
                if (!metadata) {
                    transaction.abort();
                    return;
                }
                store.put({ ...metadata, form }, key);
            };
        });
    }

    private openDatabase(): Promise<IDBDatabase> {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(CaptureDraftService.databaseName, 1);
            request.onupgradeneeded = () => {
                request.result.createObjectStore('drafts');
                request.result.createObjectStore('videos');
            };
            request.onsuccess = () => {
                const database = request.result;
                database.onversionchange = () => database.close();
                resolve(database);
            };
            request.onerror = () => {
                reject(request.error ?? new Error('Could not open the capture drafts database.'));
            };
        });
    }

    private async transact<T>(
        stores: string[],
        mode: IDBTransactionMode,
        run: (transaction: IDBTransaction) => T,
    ): Promise<T> {
        const database = await this.openDatabase();
        try {
            return await new Promise<T>((resolve, reject) => {
                const transaction = database.transaction(stores, mode);
                transaction.onabort = () => {
                    reject(transaction.error ?? new Error('Capture draft transaction failed.'));
                };
                try {
                    const result = run(transaction);
                    transaction.oncomplete = () => resolve(result);
                } catch (error) {
                    transaction.abort();
                    reject(error instanceof Error ? error : new Error(String(error)));
                }
            });
        } finally {
            database.close();
        }
    }
}
