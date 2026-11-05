import { DownloadFile } from './downloadFile';
import { sha256Hex } from 'src/lib/utils/sha256Hex';

export class DiskDownloadFile extends DownloadFile {
    private constructor(
        private readonly directory: FileSystemDirectoryHandle,
        readonly name: string,
        private handle: FileSystemFileHandle | null,
        size: number,
    ) {
        super(size);
    }

    static isAvailable(): boolean {
        return (
            typeof navigator !== 'undefined' &&
            typeof navigator.storage?.getDirectory === 'function' &&
            typeof crypto !== 'undefined' &&
            typeof crypto.subtle?.digest === 'function'
        );
    }

    static async open(url: string): Promise<DiskDownloadFile> {
        const name = await sha256Hex(url);
        const root = await navigator.storage.getDirectory();
        const directory = await root.getDirectoryHandle('resumable-downloads', { create: true });
        const handle = await directory.getFileHandle(name, { create: true });
        return new DiskDownloadFile(directory, name, handle, (await handle.getFile()).size);
    }

    protected async write(offset: number, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
        await this.updateStorage((writable) =>
            writable.write({ type: 'write', position: offset, data: bytes }),
        );
    }

    protected async truncateStorage(size: number): Promise<void> {
        await this.updateStorage((writable) => writable.truncate(size));
    }

    protected async readStorage(): Promise<File> {
        return (await this.getHandle()).getFile();
    }

    protected async removeStorage(): Promise<void> {
        try {
            await this.directory.removeEntry(this.name);
        } catch (error) {
            if (!(error instanceof DOMException && error.name === 'NotFoundError')) throw error;
        }
        this.handle = null;
    }

    private async getHandle(): Promise<FileSystemFileHandle> {
        this.handle ??= await this.directory.getFileHandle(this.name, { create: true });
        return this.handle;
    }

    private async updateStorage(
        operation: (writable: FileSystemWritableFileStream) => Promise<void>,
    ): Promise<void> {
        const writable = await (await this.getHandle()).createWritable({ keepExistingData: true });
        try {
            await operation(writable);
            await writable.close();
        } catch (error) {
            await writable.abort().catch(() => undefined);
            throw error;
        }
    }
}
