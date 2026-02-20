<script setup lang="ts">
import { type FFMPEGExtractionConfig, makeDefaultFFMPEGConfig } from '../lib/splats/ffmpeg';

const config = defineModel<FFMPEGExtractionConfig>({
    required: true,
    default: makeDefaultFFMPEGConfig(),
});

const resetToDefaults = () => {
    config.value = makeDefaultFFMPEGConfig();
};
</script>

<template>
    <q-card flat bordered class="q-pa-md q-mb-md">
        <q-card-section>
            <div class="text-h6 text-weight-light">FFMPEG Extraction</div>
            <div class="text-caption text-grey">
                Convert video to image frames for the COLMAP pipeline.
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <!-- Frame Rate Settings -->
            <div class="text-subtitle2 text-primary">Sampling Rate</div>
            <q-input
                v-model.number="config.fps"
                type="number"
                label="Frames per Second (FPS)"
                hint="How many frames to extract for every second of video."
                outlined
                dense
                suffix="fps"
                :rules="[(val) => val > 0 || 'FPS must be greater than 0']"
            />

            <q-separator inset class="q-my-sm" />

            <!-- Resolution Scaling -->
            <div class="text-subtitle2 text-primary">Resolution Bounds</div>
            <p class="text-caption text-grey-7">
                Frames will be downscaled to fit within these dimensions while maintaining aspect
                ratio.
            </p>

            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.fitInWidth"
                        type="number"
                        label="Max Width"
                        suffix="px"
                        outlined
                        dense
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.fitInHeight"
                        type="number"
                        label="Max Height"
                        suffix="px"
                        outlined
                        dense
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
</style>
