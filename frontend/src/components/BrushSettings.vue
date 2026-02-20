<script setup lang="ts">
import {
    type BrushTrainingConfig,
    makeDefaultBrushConfig,
    renderModeOptions,
    alphaModeOptions,
} from '../lib/splats/brush';

const config = defineModel<BrushTrainingConfig>({
    required: true,
});

const resetDefaults = () => {
    config.value = makeDefaultBrushConfig();
};
</script>

<template>
    <div class="q-pa-md" style="max-width: 600px">
        <q-card flat bordered>
            <q-card-section>
                <div class="text-h6">Brush Training Settings</div>
                <div class="text-caption text-grey">Universal Gaussian Splatting Training</div>
            </q-card-section>

            <q-separator />

            <q-card-section class="q-gutter-y-md">
                <!-- Training Core -->
                <div class="text-subtitle2 text-primary">Core Training</div>
                <div class="row q-col-gutter-sm">
                    <div class="col-6">
                        <q-input
                            v-model.number="config.totalSteps"
                            type="number"
                            label="Total Steps"
                            outlined
                            dense
                        />
                    </div>
                    <div class="col-6">
                        <q-select
                            v-model="config.renderMode"
                            :options="renderModeOptions"
                            label="Render Mode"
                            emit-value
                            map-options
                            outlined
                            dense
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
                    label-always
                    label="SH Degree (Spherical Harmonics)"
                    class="q-mt-lg"
                />

                <!-- Refinement -->
                <q-separator />
                <div class="text-subtitle2 text-primary">Refinement & Density</div>

                <div class="row q-col-gutter-sm">
                    <div class="col-6">
                        <q-input
                            v-model.number="config.maxSplats"
                            type="number"
                            label="Max Splats"
                            outlined
                            dense
                        />
                    </div>
                    <div class="col-6">
                        <q-input
                            v-model.number="config.growthGradThreshold"
                            type="number"
                            step="0.001"
                            label="Growth Gradient Threshold"
                            hint="Lower = more aggressive densification"
                            outlined
                            dense
                        />
                    </div>
                </div>

                <div class="row q-col-gutter-sm">
                    <div class="col-6">
                        <q-input
                            v-model.number="config.refineEvery"
                            type="number"
                            label="Refine Every (Steps)"
                            outlined
                            dense
                        />
                    </div>
                    <div class="col-6">
                        <q-input
                            v-model.number="config.growthStopIter"
                            type="number"
                            label="Stop Growth At"
                            outlined
                            dense
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
                    dense
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
                    <div class="col-6">
                        <q-input
                            v-model.number="config.maxResolution"
                            type="number"
                            label="Max Resolution"
                            outlined
                            dense
                        />
                    </div>
                    <div class="col-6">
                        <q-input
                            v-model.number="config.subsampleFrames"
                            type="number"
                            label="Subsample Every Nth Frame"
                            outlined
                            dense
                        />
                    </div>
                </div>
            </q-card-section>

            <q-separator />

            <q-btn flat label="Reset Defaults" color="grey" @click="resetDefaults" />
        </q-card>
    </div>
</template>
