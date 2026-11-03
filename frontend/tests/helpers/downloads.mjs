import { webcrypto } from 'node:crypto';
import { deferred, importTypeScript } from './typescript.mjs';

export const BLOCK_BYTES = 8 * 1024 * 1024;
export const DOWNLOAD_URL = 'https://hud.test/reconstruction/splat';

export async function downloadFixture(t, { persistent = false } = {}) {
    const files = new Map();
    const records = new Map();
    const events = [];
    const requests = [];
    let fetch;
    let closeGate;
    let checkpointError;

    function fileHandle(name) {
        return {
            kind: 'file',
            async getFile() {
                const entry = files.get(name);
                if (!entry) throw new DOMException('Missing file', 'NotFoundError');
                return {
                    size: entry.bytes.byteLength,
                    async arrayBuffer() {
                        if (files.get(name) !== entry) {
                            throw new Error('File was removed before materialization');
                        }
                        events.push(['materialize', name]);
                        return entry.bytes.slice().buffer;
                    },
                };
            },
            async createWritable() {
                const entry = files.get(name);
                let bytes = entry.bytes.slice();
                return {
                    async write({ position, data }) {
                        const next = new Uint8Array(Math.max(bytes.length, position + data.length));
                        next.set(bytes);
                        next.set(data, position);
                        bytes = next;
                    },
                    async truncate(size) {
                        bytes = bytes.slice(0, size);
                    },
                    async close() {
                        if (closeGate) {
                            const gate = closeGate;
                            closeGate = undefined;
                            gate.started.resolve();
                            await gate.release.promise;
                        }
                        entry.bytes = bytes;
                        events.push(['commit', bytes.byteLength]);
                    },
                    async abort() {},
                };
            },
        };
    }

    const directory = {
        async getFileHandle(name, options = {}) {
            if (!files.has(name)) {
                if (!options.create) throw new DOMException('Missing file', 'NotFoundError');
                files.set(name, { bytes: new Uint8Array() });
            }
            return fileHandle(name);
        },
        async removeEntry(name) {
            events.push(['remove', name]);
            if (!files.delete(name)) throw new DOMException('Missing file', 'NotFoundError');
        },
        async *entries() {
            for (const name of files.keys()) yield [name, fileHandle(name)];
        },
    };

    const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    const previousCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
    Object.defineProperty(globalThis, 'navigator', {
        configurable: true,
        value: persistent
            ? {
                  storage: {
                      getDirectory: async () => ({ getDirectoryHandle: async () => directory }),
                  },
              }
            : {},
    });
    Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });
    t.after(() => {
        if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
        else delete globalThis.navigator;
        if (previousCrypto) Object.defineProperty(globalThis, 'crypto', previousCrypto);
        else delete globalThis.crypto;
    });

    class Database {
        static isAvailable() {
            return persistent;
        }
        async get(url) {
            return records.get(url) ?? null;
        }
        async list() {
            return [...records.values()];
        }
        async save(record) {
            if (checkpointError) throw checkpointError;
            events.push(['checkpoint', record.offset]);
            records.set(record.url, structuredClone(record));
        }
        async delete(url) {
            records.delete(url);
        }
    }
    class ApiError extends Error {
        constructor(message, status, body) {
            super(message);
            this.status = status;
            this.body = body;
        }
    }
    const fileContract = await importTypeScript(t, 'src/lib/downloads/downloadFile.ts', {});
    const memory = await importTypeScript(t, 'src/lib/downloads/memoryDownloadFile.ts', {
        './downloadFile': fileContract,
    });
    const disk = await importTypeScript(t, 'src/lib/downloads/diskDownloadFile.ts', {
        './downloadFile': fileContract,
    });
    const cleanup = await importTypeScript(t, 'src/lib/downloads/cleanupStaleDownloads.ts', {
        './diskDownloadFile': disk,
        './downloadsDatabase': { DownloadsDatabase: Database },
    });
    const network = await importTypeScript(t, 'src/lib/utils/network.ts', {});
    const engine = await importTypeScript(t, 'src/lib/downloads/resumableDownload.ts', {
        'src/lib/auth': {
            authFetch(url, init) {
                requests.push({ url, ...init });
                if (!fetch) throw new Error('Unexpected request');
                return fetch(url, init);
            },
        },
        'src/lib/api': { ApiError },
        'src/lib/utils/network': network,
        './cleanupStaleDownloads': cleanup,
        './diskDownloadFile': disk,
        './memoryDownloadFile': memory,
        './downloadsDatabase': { DownloadsDatabase: Database },
    });

    return {
        ...engine,
        ...disk,
        ...memory,
        ...cleanup,
        network,
        files,
        records,
        events,
        requests,
        setFetch(value) {
            fetch = value;
        },
        failCheckpoints(error) {
            checkpointError = error;
        },
        holdNextWrite() {
            closeGate = { started: deferred(), release: deferred() };
            return closeGate;
        },
        async seed({ bytes, offset = bytes.length, total = bytes.length, etag = '"v1"' }) {
            const name = await disk.DiskDownloadFile.fileName(DOWNLOAD_URL);
            files.set(name, { bytes: new Uint8Array(bytes) });
            records.set(DOWNLOAD_URL, { url: DOWNLOAD_URL, offset, total, etag });
            return name;
        },
        open: () => engine.ResumableDownload.open(DOWNLOAD_URL),
    };
}
