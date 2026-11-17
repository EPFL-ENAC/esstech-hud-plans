export class MemoryTasksDatabase {
    records = new Map();
    attachments = new Map();
    writes = [];
    closed = false;

    async clearAndClose() {
        this.closed = true;
        await this.clear();
    }

    key(ownerId, taskId) {
        return JSON.stringify([ownerId, taskId]);
    }

    async create({ snapshot, files = {} }) {
        const key = this.key(snapshot.ownerId, snapshot.id);
        if (this.records.has(key)) throw new DOMException('Duplicate task', 'ConstraintError');
        this.records.set(key, structuredClone(snapshot));
        this.attachments.set(key, new Map(Object.entries(files)));
        this.writes.push(['create', structuredClone(snapshot)]);
    }

    async save(snapshot) {
        const key = this.key(snapshot.ownerId, snapshot.id);
        if (this.records.has(key)) this.records.set(key, structuredClone(snapshot));
        this.writes.push(['save', structuredClone(snapshot)]);
    }

    async list(ownerId) {
        return [...this.records.values()]
            .filter((record) => record.ownerId === ownerId)
            .map((record) => structuredClone(record));
    }

    files(ownerId, taskId) {
        return {
            get: async (name) => {
                const file = this.attachments.get(this.key(ownerId, taskId))?.get(name);
                if (!file) throw new Error('Missing saved file');
                return file;
            },
        };
    }

    async delete(ownerId, taskId) {
        const key = this.key(ownerId, taskId);
        this.records.delete(key);
        this.attachments.delete(key);
        this.writes.push(['delete', ownerId, taskId]);
    }

    async clear() {
        this.records.clear();
        this.attachments.clear();
    }
}
