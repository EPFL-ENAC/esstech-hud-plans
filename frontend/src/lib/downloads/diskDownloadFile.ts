import { assertTruncation, type DownloadFile } from './downloadFile';

export class DiskDownloadFile implements DownloadFile {
    private constructor(
        private readonly directory: FileSystemDirectoryHandle,
        readonly name: string,
        private handle: FileSystemFileHandle | null,
        private byteLength: number,
    ) {}

    static isStorageAvailable(): boolean {
        return (
            typeof navigator !== 'undefined' &&
            typeof crypto !== 'undefined' &&
            typeof navigator.storage?.getDirectory === 'function' &&
            typeof crypto.subtle?.digest === 'function'
        );
    }

    static async fileName(url: string): Promise<string> {
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url));
        const hash = Array.from(new Uint8Array(digest), (byte) =>
            byte.toString(16).padStart(2, '0'),
        ).join('');
        return `${hash}.part`;
    }

    static async hashUrlAndOpen(url: string): Promise<DiskDownloadFile> {
        const directory = await this.getDirectory();
        const name = await this.fileName(url);
        const handle = await directory.getFileHandle(name, { create: true });
        return new DiskDownloadFile(directory, name, handle, (await handle.getFile()).size);
    }

    static async list(): Promise<DiskDownloadFile[]> {
        const directory = await this.getDirectory();
        const files: DiskDownloadFile[] = [];
        for await (const [name, handle] of directory.entries()) {
            if (handle.kind === 'file' && name.endsWith('.part')) {
                const fileHandle = await directory.getFileHandle(name);
                files.push(
                    new DiskDownloadFile(
                        directory,
                        name,
                        fileHandle,
                        (await fileHandle.getFile()).size,
                    ),
                );
            }
        }
        return files;
    }

    private static async getDirectory(): Promise<FileSystemDirectoryHandle> {
        const root = await navigator.storage.getDirectory();
        return root.getDirectoryHandle('downloads', { create: true });
    }

    get size(): number {
        return this.byteLength;
    }

    async append(bytes: Uint8Array<ArrayBuffer>): Promise<void> {
        const handle = await this.getHandle();
        const writable = await handle.createWritable({ keepExistingData: true });
        try {
            await writable.write({ type: 'write', position: this.byteLength, data: bytes });
            await writable.close();
        } catch (error) {
            await writable.abort().catch(() => undefined);
            throw error;
        }
        this.byteLength += bytes.byteLength;
    }

    async truncate(size: number): Promise<void> {
        assertTruncation(size, this.byteLength);
        const handle = await this.getHandle();
        const writable = await handle.createWritable({ keepExistingData: true });
        try {
            await writable.truncate(size);
            await writable.close();
        } catch (error) {
            await writable.abort().catch(() => undefined);
            throw error;
        }
        this.byteLength = size;
    }

    async toBlob(): Promise<Blob> {
        const file = await (await this.getHandle()).getFile();
        // Detach the bytes from OPFS before the coordinator removes the file.
        return new Blob([await file.arrayBuffer()]);
    }

    async remove(): Promise<void> {
        try {
            await this.directory.removeEntry(this.name);
        } catch (error) {
            if (!(error instanceof DOMException && error.name === 'NotFoundError')) throw error;
        }
        this.handle = null;
        this.byteLength = 0;
    }

    private async getHandle(): Promise<FileSystemFileHandle> {
        if (!this.handle) {
            this.handle = await this.directory.getFileHandle(this.name, { create: true });
        }
        return this.handle;
    }
}
