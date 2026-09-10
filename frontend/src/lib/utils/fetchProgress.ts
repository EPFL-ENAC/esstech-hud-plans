import { authFetch } from 'src/lib/auth';
import { ApiError } from 'src/lib/buildings';

export interface FetchProgress {
    loaded: number; // bytes
    total: number; // bytes
}

function readTotal(response: Response): number {
    const raw = response.headers.get('x-file-size') ?? response.headers.get('content-length');
    const total = Number(raw);
    return Number.isFinite(total) && total > 0 ? total : 0;
}

export async function downloadWithProgress(
    url: string | URL,
    init: RequestInit,
    onProgress?: (progress: FetchProgress) => void,
): Promise<ArrayBuffer> {
    const response = await authFetch(url, init);
    if (!response.ok) {
        throw new ApiError(`Request failed with HTTP ${response.status}`, response.status, null);
    }
    if (response.body === null) {
        return response.arrayBuffer();
    }

    const total = readTotal(response);
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let received = 0;
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.byteLength;
        onProgress?.({ loaded: received, total });
    }
    const body = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) {
        body.set(chunk, offset);
        offset += chunk.byteLength;
    }
    return body.buffer;
}

export function formatMb(bytes: number): string {
    if (bytes <= 0) return '0';
    return (bytes / 1024 / 1024).toFixed(1);
}
