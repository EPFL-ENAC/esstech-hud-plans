import { webcrypto } from 'node:crypto';
import { deferred, importTypeScript } from './typescript.mjs';

export const BLOCK_BYTES = 8 * 1024 * 1024;
export const DOWNLOAD_URL = 'https://hud.test/reconstruction/splat';

export async function downloadFixture(t, { persistent = false, locksAvailable = true } = {}) {
    const files = new Map();
    const records = new Map();
    const locks = new Set();
    const events = [];
    const requests = [];
    let fetch;
    let writeGate;
    let writeError;
    let checkpointError;
    let removeError;

    const directory = {
        async getFileHandle(name, { create } = {}) {
            if (!files.has(name)) {
                if (!create) throw new DOMException('Missing file', 'NotFoundError');
                files.set(name, new Uint8Array());
            }
            return {
                async getFile() {
                    const bytes = files.get(name);
                    const file = new File([bytes], name);
                    // Library code must return the file without materializing its bytes.
                    const original = file.arrayBuffer.bind(file);
                    file.arrayBuffer = () => {
                        events.push(['materialize', name]);
                        return original();
                    };
                    return file;
                },
                async createWritable(options) {
                    if (writeError) throw writeError;
                    let bytes = options.keepExistingData
                        ? files.get(name).slice()
                        : new Uint8Array();
                    return {
                        async write({ position, data }) {
                            const next = new Uint8Array(
                                Math.max(bytes.length, position + data.length),
                            );
                            next.set(bytes);
                            next.set(data, position);
                            bytes = next;
                        },
                        async truncate(size) {
                            bytes = bytes.slice(0, size);
                        },
                        async close() {
                            if (writeGate) {
                                const gate = writeGate;
                                writeGate = undefined;
                                gate.started.resolve();
                                await gate.release.promise;
                            }
                            files.set(name, bytes);
                            events.push(['commit', bytes.length]);
                        },
                        async abort() {
                            events.push(['abort-write']);
                        },
                    };
                },
            };
        },
        async removeEntry(name) {
            if (removeError) throw removeError;
            events.push(['remove', name]);
            if (!files.delete(name)) throw new DOMException('Missing file', 'NotFoundError');
        },
    };

    const lockManager = {
        async request(name, options, operation) {
            if (!options.ifAvailable) throw new Error('Expected non-blocking lock acquisition');
            if (locks.has(name)) return operation(null);
            locks.add(name);
            try {
                return await operation({ name });
            } finally {
                locks.delete(name);
            }
        },
    };
    for (const [name, value] of Object.entries({
        navigator: {
            ...(persistent && {
                storage: {
                    getDirectory: async () => ({
                        getDirectoryHandle: async (name) => {
                            if (name !== 'resumable-downloads') throw new Error('Wrong directory');
                            return directory;
                        },
                    }),
                },
            }),
            ...(locksAvailable && { locks: lockManager }),
        },
        crypto: webcrypto,
    })) {
        const previous = Object.getOwnPropertyDescriptor(globalThis, name);
        Object.defineProperty(globalThis, name, { configurable: true, value });
        t.after(() => {
            if (previous) Object.defineProperty(globalThis, name, previous);
            else delete globalThis[name];
        });
    }

    class Database {
        static isAvailable() {
            return persistent;
        }
        async get(url) {
            return structuredClone(records.get(url) ?? null);
        }
        async save(record) {
            if (checkpointError) throw checkpointError;
            events.push(['checkpoint', record.committedBytes, record.complete]);
            records.set(record.url, structuredClone(record));
        }
        async delete(url) {
            events.push(['delete-record']);
            records.delete(url);
        }
    }
    class ApiError extends Error {
        constructor(message, status) {
            super(message);
            this.status = status;
        }
    }

    const base = 'src/lib/resumableDownload/';
    const contract = await importTypeScript(t, `${base}downloadFile.ts`, {});
    const hashing = await importTypeScript(t, 'src/lib/utils/sha256Hex.ts', {});
    const ranges = await importTypeScript(t, 'src/lib/utils/contentRange.ts', {});
    const disk = await importTypeScript(t, `${base}diskDownloadFile.ts`, {
        './downloadFile': contract,
        'src/lib/utils/sha256Hex': hashing,
    });
    const memory = await importTypeScript(t, `${base}memoryDownloadFile.ts`, {
        './downloadFile': contract,
    });
    const network = await importTypeScript(t, 'src/lib/utils/network.ts', {});
    const engine = await importTypeScript(t, `${base}resumableDownload.ts`, {
        'src/lib/auth': {
            authFetch(url, init) {
                requests.push({ url, ...init });
                if (!fetch) throw new Error('Unexpected request');
                return fetch(url, init);
            },
        },
        'src/lib/api': { ApiError },
        'src/lib/utils/contentRange': ranges,
        './diskDownloadFile': disk,
        './memoryDownloadFile': memory,
        './downloadsDatabase': { DownloadsDatabase: Database },
        'src/lib/utils/network': network,
    });

    return {
        ...contract,
        ...disk,
        ...memory,
        ...engine,
        files,
        records,
        events,
        requests,
        locks,
        setFetch(value) {
            fetch = value;
        },
        failWrites(error) {
            writeError = error;
        },
        failCheckpoints(error) {
            checkpointError = error;
        },
        failRemoval(error) {
            removeError = error;
        },
        holdNextWrite() {
            writeGate = { started: deferred(), release: deferred() };
            return writeGate;
        },
        async seed({
            bytes,
            offset = bytes.length,
            total = bytes.length,
            etag = '"v1"',
            complete = false,
        }) {
            const file = await disk.DiskDownloadFile.open(DOWNLOAD_URL);
            files.set(file.name, new Uint8Array(bytes));
            records.set(DOWNLOAD_URL, {
                url: DOWNLOAD_URL,
                committedBytes: offset,
                totalBytes: total,
                etag,
                complete,
            });
            return file.name;
        },
        open: (url = DOWNLOAD_URL) => engine.ResumableDownload.open(url),
    };
}
