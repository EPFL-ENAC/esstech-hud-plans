export class MemoryLocalUploadsRegistry {
    records = new Map();
    files = new Map();

    key(ownerId, localUploadId) {
        return JSON.stringify([ownerId, localUploadId]);
    }

    async create(ownerId, file) {
        if (file.size <= 0) {
            throw Object.assign(new Error('Upload file is empty'), { status: 400 });
        }

        const record = {
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

        const key = this.key(ownerId, record.id);
        this.records.set(key, structuredClone(record));
        this.files.set(key, file);

        return structuredClone(record);
    }

    async get(ownerId, localUploadId) {
        const record = this.records.get(this.key(ownerId, localUploadId));
        if (!record) throw new Error('Local upload is missing.');
        return structuredClone(record);
    }

    async list(ownerId) {
        return [...this.records.values()]
            .filter((record) => record.ownerId === ownerId)
            .map((record) => structuredClone(record));
    }

    async getFile(ownerId, localUploadId) {
        const file = this.files.get(this.key(ownerId, localUploadId));
        if (!file) throw new Error('Local upload file is missing.');
        return file;
    }

    async setRemote(ownerId, localUploadId, remote) {
        const record = await this.get(ownerId, localUploadId);

        if (
            record.remote !== null &&
            (record.remote.uploadId !== remote.uploadId ||
                record.remote.uploadUrl !== remote.uploadUrl)
        ) {
            throw new Error('Local upload already has a different remote upload.');
        }

        this.records.set(this.key(ownerId, localUploadId), {
            ...record,
            remote: structuredClone(remote),
        });
    }
}
