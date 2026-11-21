import type { BuildingSelection } from './buildings';
import {
    makeDefaultReconstructionSettings,
    type ReconstructionPreset,
    type ReconstructionSettingsConfig,
} from './reconstruction-settings';

type UploadActivity = { phase?: 'uploading' | 'failed' };

type LinkedDraftSource = { uploadId: string } & (
    | (UploadActivity & { completed?: never })
    | { completed: true; phase?: never }
);

type LocalDraftSourceInfo = { localVideo: true } & UploadActivity;

export type CaptureDraftSourceInfo = LinkedDraftSource | LocalDraftSourceInfo;
export type CaptureDraftSource = LinkedDraftSource | ({ video: Blob } & UploadActivity);

export type CaptureDraftUploadChange =
    | { phase: 'uploading'; uploadId?: string }
    | { phase: 'uploaded'; uploadId: string }
    | { phase: 'failed' };

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
    source: CaptureDraftSourceInfo;
    form: CaptureDraftForm;
}

export class CaptureDraftService {
    static readonly databaseName = 'hud-capture-drafts';
    private static readonly uploadEvents = new EventTarget();

    listenForUploadChanges(
        draftId: string,
        { ownerId }: { ownerId: string },
        listener: (source: CaptureDraftSourceInfo) => void,
    ): () => void {
        const key = JSON.stringify([ownerId, draftId]);
        const receive = (event: Event) => {
            listener((event as CustomEvent<CaptureDraftSourceInfo>).detail);
        };
        CaptureDraftService.uploadEvents.addEventListener(key, receive);
        return () => CaptureDraftService.uploadEvents.removeEventListener(key, receive);
    }

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
        return { id, source: source.phase ? { video, phase: source.phase } : { video }, form };
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

    async updateUpload(
        draftId: string,
        { ownerId, change }: { ownerId: string; change: CaptureDraftUploadChange },
    ): Promise<void> {
        const key = [ownerId, draftId];
        let updatedSource: CaptureDraftSourceInfo | undefined;

        await this.transact(['drafts', 'videos'], 'readwrite', (transaction) => {
            const drafts = transaction.objectStore('drafts');
            const request = drafts.get(key);
            request.onsuccess = () => {
                const metadata = request.result as DraftMetadata | undefined;
                if (!metadata) {
                    transaction.abort();
                    return;
                }

                const current = metadata.source;
                if (change.phase === 'uploaded') {
                    updatedSource = { uploadId: change.uploadId, completed: true };
                    transaction.objectStore('videos').delete(key);
                } else {
                    if ('uploadId' in current && current.completed) return;

                    updatedSource =
                        change.phase === 'uploading' && change.uploadId !== undefined
                            ? { uploadId: change.uploadId, phase: 'uploading' }
                            : { ...current, phase: change.phase };
                }

                drafts.put({ ...metadata, source: updatedSource }, key);
            };
        });

        if (updatedSource) {
            CaptureDraftService.uploadEvents.dispatchEvent(
                new CustomEvent(JSON.stringify(key), { detail: updatedSource }),
            );
        }
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
