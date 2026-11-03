import { DiskDownloadFile } from './diskDownloadFile';
import { DownloadsDatabase } from './downloadsDatabase';

let cleanup: Promise<void> | undefined;

/** Run once, before opening new part files, so cleanup cannot delete active files. */
export function cleanupStaleDownloads(): Promise<void> {
    return (cleanup ??= reconcileDownloads());
}

async function reconcileDownloads(): Promise<void> {
    if (!DiskDownloadFile.isStorageAvailable() || !DownloadsDatabase.isAvailable()) return;

    const database = new DownloadsDatabase();
    const files = new Map((await DiskDownloadFile.list()).map((file) => [file.name, file]));
    for (const record of await database.list()) {
        const name = await DiskDownloadFile.fileName(record.url);
        if (files.has(name)) {
            files.delete(name);
        } else {
            await database.save({ ...record, offset: 0 });
        }
    }
    for (const file of files.values()) {
        await file.remove();
    }
}
