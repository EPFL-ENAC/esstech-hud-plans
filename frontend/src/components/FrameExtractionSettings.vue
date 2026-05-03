<script setup lang="ts">
import {
    type FrameExtractionConfig,
    makeDefaultFrameExtractionConfig,
    switchMode,
} from 'src/lib/splats/frameExtraction';

const config = defineModel<FrameExtractionConfig>({
    required: true,
    default: makeDefaultFrameExtractionConfig(),
});

const handleModeChange = (val: 'fixed' | 'smart') => {
    config.value = switchMode(config.value, val);
};

const resetToDefaults = () => {
    config.value = makeDefaultFrameExtractionConfig();
};
</script>

<template>
    <q-card flat bordered class="q-pa-md q-mb-md">
        <q-card-section>
            <div class="row items-center no-wrap">
                <div class="col">
                    <div class="text-h6 text-weight-light">Frame Extraction</div>
                    <div class="text-caption text-grey">
                        Define how frames are captured from source video
                    </div>
                </div>
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <!-- Section 1: General Settings -->
            <div class="text-subtitle2 text-primary">General Settings</div>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.fitInWidth"
                        type="number"
                        label="Max Width (px)"
                        outlined
                        dense
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.fitInHeight"
                        type="number"
                        label="Max Height (px)"
                        outlined
                        dense
                    />
                </div>
            </div>

            <q-separator inset class="q-my-sm" />

            <!-- Mode Selection -->
            <div class="text-subtitle2 text-primary">Capture Mode</div>
            <q-btn-toggle
                :model-value="config.mode"
                @update:model-value="handleModeChange"
                toggle-color="primary"
                flat
                outlined
                spread
                unelevated
                :options="[
                    { label: 'Fixed FPS', value: 'fixed' },
                    { label: 'Smart Picker', value: 'smart' },
                ]"
            />

            <q-separator inset class="q-my-sm" />

            <!-- Section 2: Mode Specific Config -->
            <div class="text-subtitle2 text-primary">
                {{ config.mode === 'fixed' ? 'Fixed' : 'Smart' }} Parameters
            </div>

            <!-- Fixed Mode UI -->
            <div v-if="config.mode === 'fixed'" class="column">
                <q-input
                    v-model.number="config.fps"
                    type="number"
                    label="Target FPS"
                    hint="Extracts frames at a constant interval"
                    outlined
                    dense
                    suffix="fps"
                />
            </div>

            <!-- Smart Mode UI -->
            <div v-else-if="config.mode === 'smart'" class="column q-gutter-y-md">
                <div class="row q-col-gutter-md">
                    <div class="col-6 q-mb-xl">
                        <q-input
                            v-model.number="config.min_fps"
                            type="number"
                            label="Minimum FPS"
                            hint="The guaranteed minimum number of frames to extract per second"
                            outlined
                            dense
                        />
                    </div>
                    <div class="col-6">
                        <q-input
                            v-model.number="config.distance_threshold"
                            type="number"
                            label="Distance Threshold"
                            hint="Determines the sensitivity for grouping similar frames. A lower value makes the system more sensitive to movement, resulting in more frequent bins, while a higher value allows for more visual variation and camera motion within a single bin."
                            step="0.01"
                            outlined
                            dense
                        />
                    </div>
                </div>
                <div class="q-mb-md">
                    <q-input
                        v-model.number="config.outlier_sharpness_ratio"
                        type="number"
                        label="Sharpness Outlier Ratio"
                        hint="Sets the tolerance for filtering out sudden motion blur. A frame is discarded if its sharpness is lower than this fraction of its neighbors' average (e.g., 0.5 means a frame must be at least 50% as sharp as those around it to be kept). Lower values are more forgiving of slight blur."
                        step="0.05"
                        outlined
                        dense
                    />
                </div>
            </div>
        </q-card-section>

        <q-separator />

        <q-card-actions>
            <q-btn flat label="Reset to Defaults" color="grey-7" @click="resetToDefaults" />
        </q-card-actions>
    </q-card>
</template>

<style scoped>
.text-subtitle2 {
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.75rem;
}
</style>
