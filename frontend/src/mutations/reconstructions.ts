import { useMutation, useQueryCache } from '@pinia/colada';
import { computed } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { useVideoUploadStore } from 'src/stores/videoUpload';
import {
    type BuildingSelection,
    type Reconstruction,
    type BuildingCreate,
    type BuildingFromReconstruction,
    type ReconstructionSubmission,
    ApiError,
    createBuildingFromReconstruction,
    createReconstruction,
    getFailedBuildingId,
    getFailedReconstructionId,
    getReconstructionSubmissionErrorMessage,
} from 'src/lib/buildings';
import {
    SMALL_FILE_THRESHOLD,
    UPLOAD_CHUNK_SIZE_BYTES,
    computePutQueue,
    createUploadSession,
    deleteUploadSession as deleteUploadSessionRemote,
    fetchUploadSession,
    finalizeUploadSession,
    uploadSessionChunks,
    type UploadSessionCreatePayload,
} from 'src/lib/uploads/chunkUpload';
import { buildChunkPlan, makeFileFingerprint } from 'src/lib/uploads/fileDigest';
import {
    UPLOAD_RECORD_MAX_AGE_MS,
    deleteUploadSession as deleteStoredUploadSession,
    evictStaleUploadSessions,
    findUploadSessionByFingerprint,
    saveUploadSession,
    touchUploadSession,
    waitForResume,
} from 'src/lib/localTransfers';

export type SubmitReconstructionVariables = ReconstructionSubmission & BuildingSelection;

function retainedBuildingId(
    error: unknown,
    variables: SubmitReconstructionVariables | undefined,
): string | null {
    return (
        getFailedBuildingId(error) ??
        (getFailedReconstructionId(error) ? (variables?.buildingId ?? null) : null)
    );
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'AbortError';
}

function makeCreatePayload(
    file: File,
    settings: ReconstructionSubmission['settings'],
    buildingId: string | null,
    building: BuildingCreate | null,
    plan: Array<{ index: number; size: number; sha256: string }>,
): UploadSessionCreatePayload {
    const payload: UploadSessionCreatePayload = {
        filename: file.name,
        total_size: file.size,
        chunk_size: UPLOAD_CHUNK_SIZE_BYTES,
        settings: JSON.parse(JSON.stringify(settings)) as unknown,
        chunks: plan.map(({ index, size, sha256 }) => ({ index, size, sha256 })),
    };
    if (buildingId !== null) {
        payload.building_id = buildingId;
    } else if (building !== null) {
        payload.building = JSON.parse(JSON.stringify(building)) as unknown;
    }
    return payload;
}

type VideoUploadStore = ReturnType<typeof useVideoUploadStore>;

/**
 * Chunked submit: create one upload session, PUT chunks with pause and
 * resume, then finalize. The finalize response has the same shape as the
 * single-shot responses, so the surrounding flow stays unchanged.
 */
async function submitChunked(
    videoUpload: VideoUploadStore,
    variables: SubmitReconstructionVariables,
): Promise<Reconstruction> {
    const { video: file, settings } = variables;
    const buildingId = variables.buildingId;
    const building = variables.buildingId === null ? variables.building : null;

    let controller = new AbortController();
    videoUpload.beginChunked(controller);
    let sessionId: string | null = null;

    // Best effort cleanup of stored records the server session TTL already
    // killed; the transfer never waits on it.
    void evictStaleUploadSessions(UPLOAD_RECORD_MAX_AGE_MS).catch(() => undefined);

    try {
        const plan = await buildChunkPlan(file, UPLOAD_CHUNK_SIZE_BYTES);

        // Reload resume: a stored record with the same video fingerprint
        // continues the previous upload instead of starting over.
        const stored = await findUploadSessionByFingerprint(makeFileFingerprint(file));
        if (stored !== null) {
            sessionId = stored.sessionId;
            videoUpload.setSession(sessionId);
        }

        for (;;) {
            try {
                if (sessionId === null) {
                    videoUpload.setState('creating');
                    const session = await createUploadSession(
                        makeCreatePayload(file, settings, buildingId, building, plan),
                        controller.signal,
                    );
                    sessionId = session.session_id;
                    videoUpload.setSession(sessionId);
                    await saveUploadSession({
                        sessionId,
                        file,
                        plan,
                        fingerprint: makeFileFingerprint(file),
                        updatedAt: Date.now(),
                    });
                }

                videoUpload.setState('uploading');
                const serverState = await fetchUploadSession(sessionId, controller.signal);
                const queue = computePutQueue(plan, serverState.missing_chunks);
                let sent = serverState.total_chunks - queue.length;
                videoUpload.setChunks(sent, serverState.total_chunks);

                await uploadSessionChunks({
                    sessionId,
                    file,
                    entries: queue,
                    signal: controller.signal,
                    receivedBytes: serverState.received_bytes,
                    onProgress: (value) => videoUpload.update(value),
                    onChunkDone: () => {
                        sent++;
                        videoUpload.setChunks(sent, serverState.total_chunks);
                    },
                });

                videoUpload.setState('finalizing');
                const result = await finalizeUploadSession(sessionId, controller.signal);
                await deleteStoredUploadSession(sessionId);
                videoUpload.setState('done');
                return buildingId !== null
                    ? (result as Reconstruction)
                    : (result as BuildingFromReconstruction).reconstruction;
            } catch (error) {
                if (!isAbortError(error)) {
                    if (error instanceof ApiError && error.status === 410) {
                        // The session expired server-side: the next pass
                        // starts over with a fresh session and a fresh record.
                        if (sessionId !== null) void deleteStoredUploadSession(sessionId);
                        sessionId = null;
                        continue;
                    }
                    if (videoUpload.state !== 'failed') {
                        videoUpload.fail(getReconstructionSubmissionErrorMessage(error));
                    }
                    throw error;
                }
                if (videoUpload.state === 'paused') {
                    const outcome = await waitForResume(() => videoUpload.state);
                    if (outcome === 'cancelled') throw error;
                    controller = new AbortController();
                    videoUpload.attach(controller);
                    continue;
                }
                throw error;
            }
        }
    } catch (error) {
        if (sessionId !== null) {
            // A cancellation drops the stored and server records; other
            // failures keep them so the next submission can resume.
            if (isAbortError(error)) {
                void deleteUploadSessionRemote(sessionId).catch(() => undefined);
                void deleteStoredUploadSession(sessionId);
            } else {
                void touchUploadSession(sessionId);
            }
        }
        throw error;
    }
}

export function useSubmitReconstructionMutation() {
    const queryCache = useQueryCache();
    const subject = getAuthSubject();
    const videoUpload = useVideoUploadStore();
    const mutation = useMutation<Reconstruction, SubmitReconstructionVariables, unknown>({
        mutation: async (variables) => {
            videoUpload.reset();
            if (variables.video.size <= SMALL_FILE_THRESHOLD) {
                if (variables.buildingId === null) {
                    const result = await createBuildingFromReconstruction(
                        variables.building,
                        variables,
                        videoUpload.update,
                    );
                    return result.reconstruction;
                }
                return createReconstruction(variables.buildingId, variables, videoUpload.update);
            }
            return submitChunked(videoUpload, variables);
        },
        onSettled(data, error, variables) {
            const buildingId = data?.building_id ?? retainedBuildingId(error, variables);
            if (buildingId === null) return;

            // Mark cached data stale immediately, but don't let background refresh
            // failures change the outcome of a submission that already finished.
            void Promise.all([
                queryCache.invalidateQueries({ key: ['buildings', subject, 'all'] }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'list'] }),
                queryCache.invalidateQueries({ key: ['buildings', subject, 'locations'] }),
                queryCache.invalidateQueries({
                    key: ['buildings', subject, 'detail', buildingId],
                    exact: true,
                }),
                queryCache.invalidateQueries({
                    key: ['buildings', subject, 'detail', buildingId, 'reconstructions', 'list'],
                }),
            ]).catch((error: unknown) => console.warn('Could not refresh building data', error));
        },
    });

    const destinationBuildingId = computed(
        () =>
            mutation.data.value?.building_id ??
            retainedBuildingId(mutation.error.value, mutation.variables.value),
    );
    const errorMessage = computed(() => {
        const error = mutation.error.value;
        // A paused or cancelled chunked upload is not a failure.
        if (isAbortError(error) || videoUpload.state === 'paused') return '';
        return error === null ? '' : getReconstructionSubmissionErrorMessage(error);
    });

    return { ...mutation, destinationBuildingId, errorMessage };
}
