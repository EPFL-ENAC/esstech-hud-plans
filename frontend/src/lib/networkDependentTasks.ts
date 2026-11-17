import { reactive, readonly, shallowRef } from 'vue';

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
    id?: string;
    createdAt?: number;
    ownerId: string;
    label: string;
    /** Runs once after success without delaying task completion. */
    onCompleted?(this: void, result: TResult): void | Promise<void>;
}

export interface TaskSnapshot<TData = unknown> {
    type: string;
    id: string;
    createdAt: number;
    ownerId: string;
    label: string;
    state: TaskState;
    data: TData;
}

export interface SerializedTask<TData = unknown> {
    snapshot: TaskSnapshot<TData>;
    files?: Record<string, File>;
}

export interface TaskFiles {
    get(name: string): Promise<File>;
}

export class TaskPersistenceError extends Error {
    constructor(cause: unknown) {
        super('Could not save pending tasks on this device.', { cause });
    }
}

export interface TaskPersistence {
    save(snapshot: TaskSnapshot): Promise<void>;
    delete(): Promise<void>;
}

export abstract class NetworkDependentTask<TResult = void> {
    readonly id: string;
    readonly createdAt: number;
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
    private persistence: TaskPersistence | null = null;
    private readonly persistenceFailure = shallowRef<TaskPersistenceError | null>(null);
    private pendingSave: Promise<void> = Promise.resolve();
    private progressTimer: ReturnType<typeof setTimeout> | null = null;
    private suspended = false;

    constructor({ id, createdAt, ownerId, label, onCompleted }: TaskOptions<TResult>) {
        this.id = id ?? crypto.randomUUID();
        this.createdAt = createdAt ?? Date.now();
        this.ownerId = ownerId;
        this.label = label;
        this.onCompleted = onCompleted;
    }

    abstract serialize(): SerializedTask;

    bindPersistence(persistence: TaskPersistence): void {
        this.persistence = persistence;
    }

    get storageFailure(): TaskPersistenceError | null {
        return this.persistenceFailure.value;
    }

    /** Allow a retained, suspended instance to rejoin its owner's queue. */
    activate(): void {
        this.suspended = false;
    }

    protected checkpoint(): Promise<void> {
        this.stopProgressCheckpoint();
        const snapshot = this.serialize().snapshot;
        const saving = (this.persistence?.save(snapshot) ?? Promise.resolve()).then(
            () => {
                this.persistenceFailure.value = null;
            },
            (error: unknown) => {
                throw this.recordPersistenceFailure(error);
            },
        );
        this.pendingSave = saving;
        return saving;
    }

    protected setProgress(progress: TaskProgress): void {
        if (
            this.suspended ||
            ['completed', 'cancelled', 'cancelling', 'pausing'].includes(this.mutableState.status)
        )
            return;
        this.mutableState.progress = progress;
        if (!this.persistence || this.storageFailure || this.progressTimer !== null) return;
        this.progressTimer = setTimeout(() => {
            this.progressTimer = null;
            void this.checkpoint().catch(() => undefined);
        }, 1000);
    }

    private stopProgressCheckpoint(): void {
        if (this.progressTimer !== null) clearTimeout(this.progressTimer);
        this.progressTimer = null;
    }

    private recordPersistenceFailure(error: unknown): TaskPersistenceError {
        const failure =
            error instanceof TaskPersistenceError ? error : new TaskPersistenceError(error);
        this.persistenceFailure.value = failure;
        this.stopProgressCheckpoint();
        if (!['completed', 'cancelled', 'cancelling'].includes(this.mutableState.status)) {
            this.attemptFailure = failure;
            this.mutableState.error = failure.message;
            this.mutableState.status = 'blocked';
            this.controller?.abort();
        }
        return failure;
    }

    private async persistTerminalState(): Promise<void> {
        await this.checkpoint();
        try {
            await this.persistence?.delete();
        } catch (error) {
            throw this.recordPersistenceFailure(error);
        }
    }

    /** Retry storage cleanup without repeating accepted or cancelled work. */
    async retryPersistence(): Promise<void> {
        try {
            if (this.mutableState.status === 'cancelling') {
                await this.cancel();
            } else if (['completed', 'cancelled'].includes(this.mutableState.status)) {
                await this.persistTerminalState();
            } else {
                await this.checkpoint();
            }
        } catch {
            // The storage error remains visible and can be retried.
        }
    }

    /** Stop local execution while keeping its durable checkpoint. */
    async suspend(): Promise<void> {
        this.suspended = true;
        this.stopProgressCheckpoint();
        if (['running', 'pausing'].includes(this.mutableState.status)) await this.pause();
        await this.waitUntilIdle();
        if (['completed', 'cancelled'].includes(this.mutableState.status)) return;
        await this.checkpoint();
    }

    dispose(): Promise<void> {
        return this.suspend();
    }

    protected serializeBase(): Omit<TaskSnapshot, 'type' | 'data'> {
        return {
            id: this.id,
            createdAt: this.createdAt,
            ownerId: this.ownerId,
            label: this.label,
            state: {
                ...this.mutableState,
                progress: this.mutableState.progress ? { ...this.mutableState.progress } : null,
            },
        };
    }

    protected restoreState(state: TaskState): void {
        Object.assign(this.mutableState, {
            ...state,
            status: ['running', 'pausing'].includes(state.status) ? 'queued' : state.status,
            progress: state.progress ? { ...state.progress } : null,
        });
    }

    /** Run one attempt; concurrent calls share this task's active attempt. */
    retryOrResume(): Promise<TResult | undefined> {
        if (this.activeAttempt) return this.activeAttempt;
        if (this.suspended || this.interruption || this.mutableState.status !== 'queued') {
            return Promise.resolve(undefined);
        }

        const controller = new AbortController();
        this.controller = controller;
        this.mutableState.status = 'running';
        this.mutableState.attempts += 1;
        this.mutableState.error = null;
        this.attemptFailure = null;

        const attempt = Promise.resolve()
            .then(async () => {
                controller.signal.throwIfAborted();
                await this.checkpoint();
                controller.signal.throwIfAborted();
                return this.resume(controller.signal);
            })
            .then(
                async (result) => {
                    if (controller.signal.aborted) return undefined;
                    this.mutableState.status = 'completed';
                    try {
                        await this.persistTerminalState();
                    } catch {
                        // Backend acceptance remains successful even if cleanup fails.
                    }
                    void this.invokeCompletionHook(result);
                    return result;
                },
                async (error: unknown): Promise<undefined> => {
                    if (controller.signal.aborted) return undefined;
                    this.recordFailure(error);
                    try {
                        await this.checkpoint();
                    } catch {
                        // checkpoint() records and exposes storage failures itself.
                    }
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
        await this.pendingSave.catch(() => undefined);
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
            action = error instanceof TaskPersistenceError ? 'blocked' : this.failureAction(error);
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
                void this.checkpoint().catch(() => undefined);
            }
            return this.interruption;
        }

        this.interruptionReason = reason;
        this.mutableState.status = reason === 'cancel' ? 'cancelling' : 'pausing';
        this.stopProgressCheckpoint();
        const attempt = this.activeAttempt;
        this.controller?.abort();
        // Queue the interruption marker before waiting for transport cleanup.
        const marker = this.checkpoint();
        void marker.catch(() => undefined);

        const interruption = Promise.resolve()
            .then(async () => {
                await this.invokeInterruptionHook(reason);
                await attempt;
                if (reason === 'pause' && this.interruptionReason === 'cancel') {
                    await this.invokeInterruptionHook('cancel');
                }
                await marker;
                await this.pendingSave;
                if (this.interruptionReason === 'cancel') {
                    this.mutableState.status = 'cancelled';
                    await this.persistTerminalState();
                } else {
                    this.mutableState.status = 'queued';
                    await this.checkpoint();
                }
            })
            .catch((error: unknown) => {
                this.recordPersistenceFailure(error);
                if (this.interruptionReason === 'cancel') {
                    this.mutableState.status = 'cancelling';
                }
            })
            .finally(() => {
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
