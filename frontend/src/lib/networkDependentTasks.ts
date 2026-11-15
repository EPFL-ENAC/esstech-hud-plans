import { reactive, readonly } from 'vue';

export type TaskStatus =
    | 'queued'
    | 'running'
    | 'pausing'
    | 'waiting'
    | 'blocked'
    | 'failed'
    | 'cancelling'
    | 'cancelled'
    | 'completed';

export interface TaskProgress {
    completed: number;
    total: number | null;
}

export interface TaskState {
    status: TaskStatus;
    attempts: number;
    progress: TaskProgress | null;
    message: string | null;
    error: string | null;
}

export type FailureAction = 'retry' | 'blocked' | 'failed';
export type InterruptionReason = 'pause' | 'cancel';

export interface TaskOptions<TResult = void> {
    ownerId: string;
    label: string;
    /** Runs once after success without delaying task completion. */
    onCompleted?(this: void, result: TResult): void | Promise<void>;
}

export abstract class NetworkDependentTask<TResult = void> {
    readonly id = crypto.randomUUID();
    readonly createdAt = Date.now();
    readonly ownerId: string;
    readonly label: string;

    protected readonly mutableState = reactive<TaskState>({
        status: 'queued',
        attempts: 0,
        progress: null,
        message: null,
        error: null,
    });

    readonly state = readonly(this.mutableState);

    private controller: AbortController | null = null;
    private activeAttempt: Promise<TResult | undefined> | null = null;
    private attemptFailure: unknown = null;
    private interruption: Promise<void> | null = null;
    private interruptionReason: InterruptionReason | null = null;
    private readonly onCompleted: TaskOptions<TResult>['onCompleted'];

    constructor({ ownerId, label, onCompleted }: TaskOptions<TResult>) {
        this.ownerId = ownerId;
        this.label = label;
        this.onCompleted = onCompleted;
    }

    /** Run one attempt; concurrent calls share this task's active attempt. */
    retryOrResume(): Promise<TResult | undefined> {
        if (this.activeAttempt) return this.activeAttempt;
        if (this.interruption || this.mutableState.status !== 'queued') {
            return Promise.resolve(undefined);
        }

        const controller = new AbortController();
        this.controller = controller;
        this.mutableState.status = 'running';
        this.mutableState.attempts += 1;
        this.mutableState.error = null;
        this.attemptFailure = null;

        const attempt = Promise.resolve()
            .then(() => {
                controller.signal.throwIfAborted();
                return this.resume(controller.signal);
            })
            .then(
                (result) => {
                    if (!controller.signal.aborted) {
                        this.mutableState.status = 'completed';
                        void this.invokeCompletionHook(result);
                        return result;
                    }
                },
                (error: unknown): undefined => {
                    if (!controller.signal.aborted) this.recordFailure(error);
                    return undefined;
                },
            )
            .finally(() => {
                if (this.controller === controller) this.controller = null;
                if (this.activeAttempt === attempt) this.activeAttempt = null;
            });

        this.activeAttempt = attempt;
        return attempt;
    }

    get failure(): unknown {
        return this.attemptFailure;
    }

    requestRetry(): void {
        if (
            this.interruption ||
            !['queued', 'waiting', 'blocked', 'failed'].includes(this.mutableState.status)
        ) {
            return;
        }

        this.mutableState.error = null;
        this.attemptFailure = null;
        this.mutableState.status = 'queued';
    }

    pause(): Promise<void> {
        return this.interrupt('pause');
    }

    cancel(): Promise<void> {
        return this.interrupt('cancel');
    }

    /** Wait for this task's operation and interruption cleanup. */
    async waitUntilIdle(): Promise<void> {
        await this.activeAttempt;
        await this.interruption;
    }

    /**
     * Resume from checkpoints retained by the subclass. Honor the signal and
     * stop reporting progress after interruption. Replayable mutations must
     * be idempotent or reconcile the previous attempt before submitting again.
     * Subclasses update progress/message; the base class manages lifecycle.
     */
    protected abstract resume(signal: AbortSignal): Promise<TResult>;

    /** Override for transports needing explicit, repeatable pause/cancel calls. */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Subclasses inspect the reason.
    protected onInterrupt(_reason: InterruptionReason): Promise<void> {
        return Promise.resolve();
    }

    /** "retry" means wait for reconnect or manual Retry. */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Subclasses classify the error.
    protected failureAction(_error: unknown): FailureAction {
        return 'failed';
    }

    private async invokeCompletionHook(result: TResult): Promise<void> {
        try {
            await this.onCompleted?.(result);
        } catch (error) {
            console.warn('Task completion callback failed', error);
        }
    }

    private recordFailure(error: unknown): void {
        let action: FailureAction = 'failed';
        try {
            action = this.failureAction(error);
        } catch (classificationError) {
            console.warn('Could not classify task failure', classificationError);
        }

        this.attemptFailure = error;
        this.mutableState.error = error instanceof Error ? error.message || null : null;
        this.mutableState.status = action === 'retry' ? 'waiting' : action;
    }

    private interrupt(reason: InterruptionReason): Promise<void> {
        if (this.mutableState.status === 'completed' || this.mutableState.status === 'cancelled') {
            return Promise.resolve();
        }

        if (this.interruption) {
            if (reason === 'cancel') {
                this.interruptionReason = 'cancel';
                this.mutableState.status = 'cancelling';
            }
            return this.interruption;
        }

        this.interruptionReason = reason;
        this.mutableState.status = reason === 'cancel' ? 'cancelling' : 'pausing';
        const attempt = this.activeAttempt;
        this.controller?.abort();

        const interruption = Promise.resolve()
            .then(async () => {
                await this.invokeInterruptionHook(reason);
                await attempt;
                if (reason === 'pause' && this.interruptionReason === 'cancel') {
                    await this.invokeInterruptionHook('cancel');
                }
            })
            .finally(() => {
                this.mutableState.status =
                    this.interruptionReason === 'cancel' ? 'cancelled' : 'queued';
                this.interruptionReason = null;
                this.interruption = null;
            });

        this.interruption = interruption;
        return interruption;
    }

    private async invokeInterruptionHook(reason: InterruptionReason): Promise<void> {
        try {
            await this.onInterrupt(reason);
        } catch (error) {
            console.warn(`Could not complete task ${reason} cleanup`, error);
        }
    }
}
