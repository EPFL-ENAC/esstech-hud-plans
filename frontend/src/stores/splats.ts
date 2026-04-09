import { defineStore } from 'pinia';
import type { BlueprintConfig } from 'src/lib/splats/blueprint';
import type { BrushTrainingConfig } from 'src/lib/splats/brush';
import type { ColmapConfig } from 'src/lib/splats/colmap';
import type { FFMPEGExtractionConfig } from 'src/lib/splats/ffmpeg';
import { AsyncResult, delay, type ErrorBase } from 'unwrapped/core';
import { baseUrl } from 'boot/api';
import type { ColmapSparseEvaluation } from 'src/lib/splats/evaluations';

export interface SplatPipelineSettings {
    video_path: string;
    ffmpeg: FFMPEGExtractionConfig;
    colmap: ColmapConfig;
    brush: BrushTrainingConfig;
    blueprint: BlueprintConfig;
}

export interface SplatPipelineStep<T extends object, E extends object = object> {
    status: 'running' | 'completed' | 'failed';
    progress: number;
    submitted_at?: string | null;
    started_at: string | null;
    finished_at: string | null;
    settings: T;
    evaluation?: E;
    command: string | string[];
    logs: string[];
    return_code: number;
}

export interface SplatPipelineStatus {
    overall_status: 'running' | 'completed' | 'failed';
    progress: number;
    message?: string;
    started_at: string | null;
    finished_at: string | null;
    name: string;
    settings: SplatPipelineSettings;
    steps_list: string[];

    output: {
        splat_path: string;
        blueprints: string[];
    };

    steps: {
        ffmpeg: SplatPipelineStep<FFMPEGExtractionConfig>;
        colmap: SplatPipelineStep<ColmapConfig, ColmapSparseEvaluation>;
        brush: SplatPipelineStep<BrushTrainingConfig>;
        blueprint_extraction?: SplatPipelineStep<BlueprintConfig>;
    };
}

export function hasBlueprintGeneration(status: SplatPipelineStatus): boolean {
    return status.steps_list?.includes('blueprint_extraction') ?? false;
}

export const useSplatStore = defineStore('splat', () => {
    const loaders: Record<
        string,
        AsyncResult<SplatPipelineStatus, ErrorBase, SplatPipelineStatus>
    > = {};

    function getStatus(generationId: string) {
        if (!loaders[generationId]) {
            loaders[generationId] = AsyncResult.run(function* (notifyProgress) {
                yield* delay(2000); // slight delay to allow for initial processing

                while (true) {
                    try {
                        const fetched = yield* AsyncResult.fromValuePromise(
                            fetch(`${baseUrl}/splats/status/${generationId}`),
                        );
                        if (fetched.ok) {
                            const statusData: SplatPipelineStatus =
                                yield* AsyncResult.fromValuePromise(fetched.json());
                            const knownStatuses = ['running', 'completed', 'failed'];
                            if (knownStatuses.includes(statusData.overall_status)) {
                                notifyProgress(statusData);
                                if (
                                    statusData.overall_status === 'completed' ||
                                    statusData.overall_status === 'failed'
                                ) {
                                    return yield* AsyncResult.ok(statusData);
                                }
                            }
                        }
                    } catch (e) {
                        // Log error but continue polling - don't fail the entire operation
                        console.warn(`Failed to fetch status for ${generationId}, retrying...`, e);
                    }

                    yield* delay(2000);
                }
            });
        }
        return loaders[generationId];
    }

    function getSplat(generationId: string) {
        return AsyncResult.run<ArrayBuffer, ErrorBase, SplatPipelineStatus>(function* () {
            const status = yield* getStatus(generationId);
            if (status.overall_status !== 'completed') {
                return yield* AsyncResult.errTag('generation_failed', status.message);
            }

            const fetched = yield* AsyncResult.fromValuePromise(
                fetch(`${baseUrl}/splats/get/${generationId}`),
            );

            if (!fetched.ok) {
                return yield* AsyncResult.errTag('generation_retrieval_failed');
            }

            return yield* AsyncResult.fromValuePromise(fetched.arrayBuffer());
        });
    }

    return {
        getStatus,
        getSplat,
    };
});
