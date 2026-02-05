import { defineStore } from "pinia";
import type { BrushTrainingConfig } from "src/lib/splats/brush";
import type { ColmapConfig } from "src/lib/splats/colmap";
import type { FFMPEGExtractionConfig } from "src/lib/splats/ffmpeg";
import { AsyncResult, delay, type ErrorBase } from "unwrapped/core";

export interface SplatPipelineSettings {
    video_path: string;
    ffmpeg: FFMPEGExtractionConfig;
    colmap: ColmapConfig;
    brush: BrushTrainingConfig;
}

export interface SplatPipelineStep<T extends object> {
    status: "running" | "completed" | "failed";
    progress: number;
    started_at: string | null;
    finished_at: string | null;
    settings: T;
    command: string | string[];
    logs: string[];
    return_code: number;
}

export interface SplatPipelineStatus {
    overall_status: "running" | "completed" | "failed";
    progress: number;
    message?: string;
    started_at: string | null;
    finished_at: string | null;
    name: string;
    settings: SplatPipelineSettings;

    output: {
        splat_path: string;
        blueprints: string[];
    }

    steps: {
        ffmpeg: SplatPipelineStep<FFMPEGExtractionConfig>
        colmap: SplatPipelineStep<ColmapConfig>
        brush: SplatPipelineStep<BrushTrainingConfig>
        blueprint_extraction: SplatPipelineStep<object>;
    }
}

export const useSplatStore = defineStore('splat', () => {
    const loaders: Record<string, AsyncResult<SplatPipelineStatus, ErrorBase, SplatPipelineStatus>> = {};

    function getStatus(generationId: string) {
        if (!loaders[generationId]) {
            loaders[generationId] = AsyncResult.run(function* (notifyProgress) {
                yield* delay(5000); // slight delay to allow for initial processing

                while (true) {
                    const fetched = yield* AsyncResult.fromValuePromise(
                        fetch(`http://localhost:8000/splats/status/${generationId}`)
                    );
                    if (fetched.ok) {
                        const statusData: SplatPipelineStatus = yield* AsyncResult.fromValuePromise(fetched.json());
                        notifyProgress(statusData);
                        if (statusData.overall_status === "completed" || statusData.overall_status === "failed") {
                            return yield* AsyncResult.ok(statusData);
                        }
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
                return yield* AsyncResult.errTag("generation_failed", status.message);
            }

            const fetched = yield* AsyncResult.fromValuePromise(
                fetch(`http://localhost:8000/splats/get/${generationId}`)
            );

            if (!fetched.ok) {
                return yield* AsyncResult.errTag("generation_retrieval_failed");
            }

            return yield* AsyncResult.fromValuePromise(fetched.arrayBuffer());
        });
    }

    return {
        getStatus,
        getSplat,
    };
});