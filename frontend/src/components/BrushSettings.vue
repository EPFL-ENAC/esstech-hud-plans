<script setup lang="ts">
import {
    type BrushTrainingConfig,
    makeDefaultBrushConfig,
    renderModeOptions,
    alphaModeOptions,
} from '../lib/splats/brush';

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

const config = defineModel<BrushTrainingConfig>({
    required: true,
});

const resetDefaults = () => {
    config.value = makeDefaultBrushConfig();
};
</script>

<template>
    <q-card flat :bordered="!embedded" :class="embedded ? 'embedded-settings' : 'q-pa-md q-mb-md'">
        <q-card-section>
            <div class="text-h6 text-weight-light">Brush 3D Gaussian Splats Reconstruction</div>
            <div class="text-caption text-grey">
                Train a 3D Gaussian Splat model to reconstruct the scene.
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <!-- Training Core -->
            <div class="text-subtitle2 text-primary">Core Training</div>
            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.totalSteps"
                        type="number"
                        label="Total Steps"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-select
                        v-model="config.renderMode"
                        :options="renderModeOptions"
                        label="Render Mode"
                        emit-value
                        map-options
                        outlined
                        :dense="!embedded"
                    >
                        <template v-slot:option="scope">
                            <q-item v-bind="scope.itemProps">
                                <q-item-section>
                                    <q-item-label>{{ scope.opt.label }}</q-item-label>
                                    <q-item-label caption>{{ scope.opt.desc }}</q-item-label>
                                </q-item-section>
                            </q-item>
                        </template>
                    </q-select>
                </div>
            </div>

            <q-input
                v-model.number="config.shDegree"
                :min="0"
                :max="3"
                :step="1"
                type="number"
                outlined
                :dense="!embedded"
                label="SH Degree (Spherical Harmonics)"
                class="q-mt-lg"
            />

            <!-- Refinement -->
            <q-separator />
            <div class="text-subtitle2 text-primary">Refinement & Density</div>

            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.maxSplats"
                        type="number"
                        label="Max Splats"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.growthGradThreshold"
                        type="number"
                        step="0.001"
                        label="Growth Gradient Threshold"
                        hint="Lower = more aggressive densification"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.refineEvery"
                        type="number"
                        label="Refine Every (Steps)"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.growthStopIter"
                        type="number"
                        label="Stop Growth At"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <q-separator />
            <div class="text-subtitle2 text-primary">Dataset & Performance</div>

            <q-select
                v-model="config.alphaMode"
                :options="alphaModeOptions"
                label="Alpha Channel Mode"
                emit-value
                map-options
                outlined
                :dense="!embedded"
            >
                <template v-slot:option="scope">
                    <q-item v-bind="scope.itemProps">
                        <q-item-section>
                            <q-item-label>{{ scope.opt.label }}</q-item-label>
                            <q-item-label caption>{{ scope.opt.desc }}</q-item-label>
                        </q-item-section>
                    </q-item>
                </template>
            </q-select>

            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.maxResolution"
                        type="number"
                        label="Max Resolution"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.subsampleFrames"
                        type="number"
                        label="Subsample Every Nth Frame"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <q-separator />
            <div class="text-subtitle2 text-primary">Exports</div>

            <q-input
                v-model.number="config.exportEvery"
                type="number"
                min="1"
                label="Export Every (Steps)"
                outlined
                :dense="!embedded"
            />
        </q-card-section>

        <q-separator />

        <q-btn flat no-caps label="Reset Defaults" color="grey" @click="resetDefaults" />
    </q-card>
</template>

<style scoped>
.embedded-settings > .q-card__section {
    padding: 16px 0;
}

.embedded-settings > .q-card__section:first-child {
    padding-top: 0;
}

.embedded-settings .text-h6 {
    font-size: 1rem;
    font-weight: 700;
}

.embedded-settings .text-subtitle2 {
    letter-spacing: normal;
    text-transform: none;
    font-size: 0.875rem;
}
</style>
