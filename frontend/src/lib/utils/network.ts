/* eslint-disable @typescript-eslint/prefer-promise-reject-errors -- Preserve cancellation reasons and underlying rejection identities. */

export function abortReason(signal: AbortSignal): unknown {
    return signal.reason ?? new DOMException('The operation was cancelled.', 'AbortError');
}

export function throwIfAborted(signal: AbortSignal): void {
    if (signal.aborted) throw abortReason(signal);
}

export async function withAbortController<T>(
    parentSignal: AbortSignal | undefined,
    operation: (controller: AbortController) => Promise<T>,
): Promise<T> {
    const controller = new AbortController();
    const forwardAbort = () => controller.abort(parentSignal?.reason);
    parentSignal?.addEventListener('abort', forwardAbort, { once: true });
    if (parentSignal?.aborted) forwardAbort();
    try {
        throwIfAborted(controller.signal);
        const result = await operation(controller);
        throwIfAborted(controller.signal);
        return result;
    } finally {
        parentSignal?.removeEventListener('abort', forwardAbort);
        controller.abort();
    }
}

/** Bound one network wait and abort the underlying transport when it expires. */
export function waitForNetwork<T>(
    operation: () => Promise<T>,
    controller: AbortController,
    timeoutMs = 60_000,
): Promise<T> {
    const { signal } = controller;
    if (signal.aborted) return Promise.reject(abortReason(signal));

    return new Promise<T>((resolve, reject) => {
        const cleanup = () => {
            clearTimeout(timer);
            signal.removeEventListener('abort', onAbort);
        };
        const onAbort = () => {
            cleanup();
            reject(abortReason(signal));
        };
        const timer = setTimeout(() => {
            const error = new DOMException(
                `No network response or data for ${timeoutMs / 1000} seconds.`,
                'TimeoutError',
            );
            cleanup();
            reject(error);
            controller.abort(error);
        }, timeoutMs);

        signal.addEventListener('abort', onAbort, { once: true });
        Promise.resolve()
            .then(() => {
                throwIfAborted(signal);
                return operation();
            })
            .then(
                (value) => {
                    cleanup();
                    resolve(value);
                },
                (error: unknown) => {
                    cleanup();
                    reject(error);
                },
            );
    });
}

export async function* readResponseChunks(
    response: Response,
    controller: AbortController,
): AsyncGenerator<Uint8Array> {
    const reader = response.body?.getReader();
    if (!reader) return;
    try {
        for (;;) {
            const { done, value } = await waitForNetwork(() => reader.read(), controller);
            if (done) return;
            if (value.byteLength > 0) yield value;
        }
    } finally {
        void reader.cancel().catch(() => undefined);
        reader.releaseLock();
    }
}
