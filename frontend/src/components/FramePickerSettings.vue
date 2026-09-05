<script setup lang="ts">
import { type FramePickerConfig, makeDefaultFramePickerConfig } from 'src/lib/splats/framePicker';

const config = defineModel<FramePickerConfig>({
    required: true,
    default: makeDefaultFramePickerConfig(),
});

const resetToDefaults = () => {
    config.value = makeDefaultFramePickerConfig();
};
</script>

<template>
    <q-card flat bordered class="q-pa-md q-mb-md">
        <q-card-section>
            <div class="row items-center no-wrap">
                <div class="col">
                    <div class="text-h6 text-weight-light">Frame Selection</div>
                    <div class="text-caption text-grey">
                        Filter and select the best frames based on quality and distance.
                    </div>
                </div>
                <q-toggle v-model="config.enabled" label="Enabled" left-label />
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md" :class="{ 'opacity-50': !config.enabled }">
            <div class="text-subtitle2 text-primary">Selection</div>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.min_fps"
                        type="number"
                        min="1"
                        label="Minimum FPS"
                        hint="Minimum selected-frame frequency"
                        outlined
                        dense
                        :disable="!config.enabled"
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.distance_threshold"
                        type="number"
                        label="Distance Threshold"
                        hint="Minimum movement between frames"
                        outlined
                        dense
                        min="0"
                        step="0.01"
                        :disable="!config.enabled"
                    />
                </div>
            </div>

            <q-separator inset class="q-my-sm" />

            <div class="text-subtitle2 text-primary">Motion Blur</div>
            <q-toggle
                v-model="config.remove_outliers"
                label="Remove sharpness outliers"
                :disable="!config.enabled"
            />

            <q-input
                v-model.number="config.outlier_sharpness_ratio"
                type="number"
                min="0"
                max="1"
                step="0.05"
                label="Sharpness Outlier Ratio"
                hint="Discard a frame when its sharpness falls below this fraction of its neighbors"
                outlined
                dense
                :disable="!config.enabled || !config.remove_outliers"
            />
        </q-card-section>

        <q-separator />

        <q-btn flat label="Reset to Defaults" color="grey-7" @click="resetToDefaults" />
    </q-card>
</template>

<style scoped>
.text-subtitle2 {
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.75rem;
}

.opacity-50 {
    opacity: 0.5;
    pointer-events: none;
}
</style>
