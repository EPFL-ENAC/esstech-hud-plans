/* eslint-disable @typescript-eslint/prefer-promise-reject-errors -- Preserve cancellation reasons and underlying rejection identities. */

export async function withAbortController<T>(
    parentSignal: AbortSignal | undefined,
    operation: (controller: AbortController) => Promise<T>,
): Promise<T> {
    const controller = new AbortController();
    const forwardAbort = () => controller.abort(parentSignal?.reason);
    parentSignal?.addEventListener('abort', forwardAbort, { once: true });
    if (parentSignal?.aborted) forwardAbort();
    try {
        controller.signal.throwIfAborted();
        const result = await operation(controller);
        controller.signal.throwIfAborted();
        return result;
    } finally {
        parentSignal?.removeEventListener('abort', forwardAbort);
        controller.abort();
    }
}

/** Bound one network wait and abort the underlying transport when it expires. */
export async function waitForNetwork<T>(
    operation: () => Promise<T>,
    controller: AbortController,
    timeoutMs = 60_000,
): Promise<T> {
    const { signal } = controller;
    signal.throwIfAborted();

    return new Promise<T>((resolve, reject) => {
        const cleanup = () => {
            clearTimeout(timer);
            signal.removeEventListener('abort', onAbort);
        };
        const onAbort = () => {
            cleanup();
            reject(signal.reason);
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
                signal.throwIfAborted();
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
