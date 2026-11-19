export class MemoryTasksDatabase {
    records = new Map();
    writes = [];
    closed = false;

    async clearAndClose() {
        this.closed = true;
        await this.clear();
    }

    key(ownerId, taskId) {
        return JSON.stringify([ownerId, taskId]);
    }

    async create(snapshot) {
        const key = this.key(snapshot.ownerId, snapshot.id);
        if (this.records.has(key)) throw new DOMException('Duplicate task', 'ConstraintError');
        this.records.set(key, structuredClone(snapshot));
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

    async delete(ownerId, taskId) {
        const key = this.key(ownerId, taskId);
        this.records.delete(key);
        this.writes.push(['delete', ownerId, taskId]);
    }

    async clear() {
        this.records.clear();
    }
}
