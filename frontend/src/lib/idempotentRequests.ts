import { ApiError, requestJson } from 'src/lib/api';
import type { FailureAction } from 'src/lib/networkDependentTasks';

export interface IdempotentRequestOptions extends RequestInit {
    idempotencyKey: string;
}

function isIdempotencyInProgress(error: ApiError): boolean {
    if (error.status !== 409) return false;

    const body = error.body;
    if (typeof body !== 'object' || body === null || !('detail' in body)) {
        return false;
    }

    const detail = body.detail;
    return (
        typeof detail === 'object' &&
        detail !== null &&
        'code' in detail &&
        detail.code === 'idempotency_in_progress'
    );
}

/**
 * The caller owns the key and reuses it with the same payload on every attempt.
 * An empty 204 replay response resolves to null.
 * This function performs one attempt; it does not schedule retries.
 */
export function requestIdempotentJson<T>(
    path: string,
    { idempotencyKey, ...init }: IdempotentRequestOptions,
): Promise<T | null> {
    const headers = new Headers(init.headers);
    headers.set('Idempotency-Key', idempotencyKey);

    return requestJson<T | null>(path, {
        ...init,
        headers,
    });
}

/** Opt-in retry policy for requests that are safe to replay. */
export function idempotentRequestFailureAction(error: unknown): FailureAction {
    if (error instanceof TypeError) return 'retry';
    if (!(error instanceof ApiError)) return 'failed';

    if (error.status === 401 || error.status === 403) {
        return 'blocked';
    }

    if (
        error.status === 408 ||
        error.status === 429 ||
        error.status >= 500 ||
        isIdempotencyInProgress(error)
    ) {
        return 'retry';
    }

    return 'failed';
}
