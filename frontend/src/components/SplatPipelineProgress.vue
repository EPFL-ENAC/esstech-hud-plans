<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import type { SplatPipelineStatus } from 'src/stores/splats';
import PipelineStepProgress from './PipelineStepProgress.vue';
import ColmapEvaluation from './ColmapEvaluation.vue';
import { colmapLogsParser } from 'src/lib/utils/logs';

const props = defineProps<{
    value: SplatPipelineStatus;
}>();

const router = useRouter();

function handleRelaunchBrush() {
    const splatPath = props.value.output.splat_path;
    const parts = splatPath.split('/');
    const generationId = parts[parts.indexOf('splats') + 1] as string;
    const brushSettings = props.value.steps.brush.settings;

    const query: Record<string, string | number> = {
        colmapGenerationId: generationId,
        brushTotalSteps: brushSettings.totalSteps,
        brushRenderMode: brushSettings.renderMode,
        brushShDegree: brushSettings.shDegree,
        brushMaxSplats: brushSettings.maxSplats,
        brushGrowthGradThreshold: brushSettings.growthGradThreshold,
        brushRefineEvery: brushSettings.refineEvery,
        brushGrowthStopIter: brushSettings.growthStopIter,
        brushAlphaMode: brushSettings.alphaMode,
        brushMaxResolution: brushSettings.maxResolution,
        brushSubsampleFrames: brushSettings.subsampleFrames,
    };

    void router.push({
        path: '/',
        query,
    });
}

const statusColor = computed(() => {
    if (props.value.overall_status === 'completed') return 'positive';
    if (props.value.overall_status === 'failed') return 'negative';
    return 'primary';
});

const statusText = computed(() => {
    switch (props.value.overall_status) {
        case 'completed':
            return 'Completed';
        case 'failed':
            return 'Failed';
        case 'running':
            return 'Processing...';
        case 'submitted':
            return 'Submitted';
        default:
            return 'Unknown';
    }
});
</script>

<template>
    <div class="pipeline-results">
        <!-- Overall Header -->
        <div class="q-pa-md">
            <div class="row items-center q-mb-lg">
                <h3 class="q-my-none">
                    {{ statusText }}
                </h3>

                <div class="q-ml-md">
                    <q-circular-progress
                        v-if="props.value.overall_status === 'running'"
                        indeterminate
                        rounded
                        size="50px"
                        color="primary"
                    />
                    <q-chip
                        v-else
                        :color="statusColor"
                        text-color="white"
                        class="q-ml-md"
                        icon="info"
                    >
                        {{ props.value.overall_status?.toUpperCase() || 'UNKNOWN' }}
                    </q-chip>
                </div>
            </div>
            <!-- Overall Progress Bar -->
            <q-linear-progress
                :value="props.value.progress"
                :color="statusColor"
                size="10px"
                class="q-mb-xl"
            />
        </div>

        <!-- Pipeline Steps -->
        <q-list separator class="rounded-borders">
            <pipeline-step-progress
                v-if="props.value.steps.ffmpeg"
                :step="props.value.steps.ffmpeg"
                title="FFMPEG"
            />
            <pipeline-step-progress
                v-if="props.value.steps.frame_picker"
                :step="props.value.steps.frame_picker"
                title="Frame Picker"
            />
            <pipeline-step-progress
                v-if="props.value.steps.colmap"
                :step="props.value.steps.colmap"
                :logs-parser="colmapLogsParser"
                title="Colmap"
            >
                <colmap-evaluation
                    v-if="props.value.steps.colmap.evaluation"
                    :evaluation="props.value.steps.colmap.evaluation"
                />
            </pipeline-step-progress>
            <pipeline-step-progress
                v-if="props.value.steps.brush"
                title="Brush"
                :step="props.value.steps.brush"
            />
            <pipeline-step-progress
                v-if="props.value.steps.blueprint_extraction"
                title="Blueprint Extraction"
                :step="props.value.steps.blueprint_extraction"
            />
        </q-list>

        <!-- Relaunch Brush Button (Visible when completed) -->
        <div v-if="props.value.overall_status === 'completed'" class="q-pa-md">
            <q-btn
                color="primary"
                label="Relaunch Brush Step"
                icon="refresh"
                @click="handleRelaunchBrush"
                class="full-width"
            />
        </div>

        <!-- Output Section (Visible when completed) -->
        <q-card v-if="props.value.overall_status === 'completed'" class="q-mt-lg bg-grey-1">
            <q-card-section>
                <div class="text-h6">Output Artifacts</div>
                <div class="q-mt-sm">
                    <q-item clickable v-ripple>
                        <q-item-section avatar>
                            <q-icon name="folder" color="primary" />
                        </q-item-section>
                        <q-item-section>
                            <q-item-label>Splat Path</q-item-label>
                            <q-item-label caption>
                                <div class="path">
                                    {{ props.value.output.splat_path }}
                                </div>
                            </q-item-label>
                        </q-item-section>
                    </q-item>
                </div>
            </q-card-section>
        </q-card>
    </div>
</template>

<style scoped>
.path {
    overflow: auto;
}
</style>
