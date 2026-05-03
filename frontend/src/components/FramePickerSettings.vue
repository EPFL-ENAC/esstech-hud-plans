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
            <!-- Threshold Settings -->
            <div class="text-subtitle2 text-primary">Quality & Distance</div>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.sharpness_threshold"
                        type="number"
                        label="Sharpness Threshold"
                        hint="Minimum sharpness score"
                        outlined
                        dense
                        step="0.05"
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
                        step="0.05"
                        :disable="!config.enabled"
                    />
                </div>
            </div>

            <q-separator inset class="q-my-sm" />

            <!-- Binning and Grid -->
            <div class="text-subtitle2 text-primary">Spatial Binning</div>
            <q-input
                v-model.number="config.max_bin_length"
                type="number"
                label="Max Bin Length"
                hint="Maximum number of frames to keep per spatial bin."
                outlined
                dense
                :disable="!config.enabled"
            />

            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.grid_cols"
                        type="number"
                        label="Grid Columns"
                        outlined
                        dense
                        :disable="!config.enabled"
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.grid_rows"
                        type="number"
                        label="Grid Rows"
                        outlined
                        dense
                        :disable="!config.enabled"
                    />
                </div>
            </div>
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
