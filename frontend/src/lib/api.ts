import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';

export class ApiError extends Error {
    constructor(
        message: string,
        readonly status: number,
        readonly body: unknown,
    ) {
        super(message);
    }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await authFetch(`${baseUrl}${path}`, init);
    const text = await response.text();
    let body: unknown = null;
    if (text) {
        try {
            body = JSON.parse(text) as unknown;
        } catch {
            body = text;
        }
    }
    if (!response.ok) {
        throw new ApiError(`Request failed with HTTP ${response.status}`, response.status, body);
    }
    return body as T;
}
