<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import type { ColmapSparseEvaluation } from 'src/lib/splats/evaluations';

const router = useRouter();

const props = defineProps<{
    evaluation: ColmapSparseEvaluation;
    rootGenerationId: string;
}>();

const showFullMetrics = ref(false);

function handleRelaunchWithReconstruction(modelIndex: number) {
    const query: Record<string, string | number> = {
        colmapGenerationId: props.rootGenerationId,
        colmapSparseReconstructionId: modelIndex,
    };

    void router.push({
        path: '/',
        query,
    });
}

function getScoreColor(score: number): string {
    if (score > 0.7) return 'positive';
    if (score > 0.4) return 'warning';
    return 'negative';
}

function formatValue(val: number | null | undefined): string {
    if (val === null || val === undefined) return 'N/A';
    return val.toFixed(4);
}
</script>

<template>
    <div class="sparse-evaluation-container q-gutter-y-md">
        <!-- Summary Header -->
        <div class="row items-center justify-between bg-grey-2 q-pa-md rounded-borders">
            <div class="column">
                <div class="text-h6">Sparse Reconstruction Evaluation</div>
                <div class="text-caption">
                    Models Found: {{ props.evaluation.num_models }} | Total Frames:
                    {{ props.evaluation.total_input_frames ?? 'Unknown' }}
                </div>
            </div>
            <q-btn
                :icon="showFullMetrics ? 'visibility_off' : 'visibility'"
                :label="showFullMetrics ? 'Hide Raw Metrics' : 'Show Raw Metrics'"
                flat
                color="primary"
                @click="showFullMetrics = !showFullMetrics"
            />
        </div>

        <!-- Evaluation List -->
        <div class="row q-col-gutter-md">
            <div v-for="(ev, index) in props.evaluation.evaluations" :key="index" class="col-12">
                <q-card
                    flat
                    bordered
                    :class="{ 'best-model-border': index === props.evaluation.best_model_index }"
                >
                    <q-item>
                        <q-item-section avatar>
                            <q-chip
                                :color="
                                    index === props.evaluation.best_model_index ? 'gold' : 'grey-7'
                                "
                                text-color="white"
                                :icon="
                                    index === props.evaluation.best_model_index
                                        ? 'star'
                                        : 'account_tree'
                                "
                            >
                                Model {{ ev.metrics.model_name }}
                            </q-chip>
                        </q-item-section>

                        <q-item-section>
                            <q-item-label caption>
                                Score:
                                <span
                                    :class="`text-weight-bolder text-${getScoreColor(ev.score)}`"
                                    style="font-size: 1.1rem"
                                >
                                    {{ (ev.score * 100).toFixed(1) }}%
                                </span>
                            </q-item-label>
                        </q-item-section>
                    </q-item>

                    <q-separator />

                    <q-card-section>
                        <div class="row q-col-gutter-sm">
                            <!-- Score Breakdowns -->
                            <div class="col-12 col-md-5">
                                <div class="text-subtitle2 q-mb-sm text-grey-7">
                                    Score Breakdown
                                </div>
                                <div class="q-gutter-y-xs">
                                    <div class="row justify-between">
                                        <span>Coverage</span>
                                        <q-badge outline color="blue"
                                            >{{ (ev.coverage_score * 100).toFixed(1) }}%</q-badge
                                        >
                                    </div>
                                    <div class="row justify-between">
                                        <span>Continuity</span>
                                        <q-badge outline color="purple"
                                            >{{ (ev.continuity_score * 100).toFixed(1) }}%</q-badge
                                        >
                                    </div>
                                    <div class="row justify-between">
                                        <span>Accuracy</span>
                                        <q-badge outline color="green"
                                            >{{ (ev.accuracy_score * 100).toFixed(1) }}%</q-badge
                                        >
                                    </div>
                                    <div class="row justify-between">
                                        <span>Density</span>
                                        <q-badge outline color="orange"
                                            >{{
                                                (ev.points_density_score * 100).toFixed(1)
                                            }}%</q-badge
                                        >
                                    </div>
                                    <div
                                        v-if="ev.fragmentation > 0"
                                        class="row justify-between text-negative text-italic"
                                    >
                                        <span>Fragmentation Penalty</span>
                                        <span>-{{ (ev.fragmentation * 100).toFixed(1) }}%</span>
                                    </div>
                                </div>
                            </div>

                            <!-- Key Hardware/Size Metrics -->
                            <div class="col-12 col-md-7">
                                <div class="text-subtitle2 q-mb-sm text-grey-7">Key Statistics</div>
                                <q-list dense>
                                    <q-item class="q-pa-none">
                                        <q-item-section>Points 3D</q-item-section>
                                        <q-item-section side>{{
                                            ev.metrics.num_points3D.toLocaleString()
                                        }}</q-item-section>
                                    </q-item>
                                    <q-item class="q-pa-none">
                                        <q-item-section>Registered Images</q-item-section>
                                        <q-item-section side>{{
                                            ev.metrics.num_registered_images
                                        }}</q-item-section>
                                    </q-item>
                                    <q-item class="q-pa-none">
                                        <q-item-section>Median Error</q-item-section>
                                        <q-item-section side>
                                            {{
                                                formatValue(
                                                    ev.metrics.reprojection_error_stats.median,
                                                )
                                            }}
                                            px
                                        </q-item-section>
                                    </q-item>
                                </q-list>
                            </div>
                        </div>

                        <!-- Raw Metrics (JSON) -->
                        <q-slide-transition>
                            <div v-if="showFullMetrics" class="q-mt-md">
                                <q-separator class="q-mb-md" />
                                <div class="text-subtitle2 q-mb-xs">Full Raw Metrics:</div>
                                <pre
                                    class="metrics-pre bg-black text-lime-13 q-pa-md rounded-borders"
                                >
                                    {{ JSON.stringify(ev.metrics, null, 2) }}
                                </pre>
                            </div>
                        </q-slide-transition>
                    </q-card-section>

                    <q-card-section>
                        <q-btn
                            outline
                            color="primary"
                            icon="play_arrow"
                            label="Launch Brush with this reconstruction"
                            @click="handleRelaunchWithReconstruction(index)"
                        />
                    </q-card-section>
                </q-card>
            </div>
        </div>
    </div>
</template>

<style scoped>
.best-model-border {
    border: 2px solid var(--q-primary);
    box-shadow: 0 0 10px rgba(var(--q-primary), 0.2);
}

.metrics-pre {
    max-height: 400px;
    overflow-y: auto;
    font-size: 0.75rem;
    white-space: pre-wrap;
}

.text-gold {
    color: #ffd700;
}
.bg-gold {
    background: #ffd700;
}
</style>
