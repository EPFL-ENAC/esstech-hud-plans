<script setup lang="ts">
import { computed } from 'vue';
import { type BlueprintConfig, makeDefaultBlueprintConfig } from '../lib/splats/blueprint';

const config = defineModel<BlueprintConfig>({
    required: true,
    default: makeDefaultBlueprintConfig(),
});

const resetToDefaults = () => {
    config.value = makeDefaultBlueprintConfig();
};

const isEnabled = computed(() => config.value.enabled);

const cardClasses = computed(() => ({
    'q-pa-md': true,
    'q-mb-md': true,
    'text-grey-5': !isEnabled.value,
}));
</script>

<template>
    <q-card flat bordered :class="cardClasses">
        <q-card-section class="row items-center justify-between">
            <div>
                <div class="text-h6 text-weight-light">Blueprint Extraction (Optional)</div>
                <div class="text-caption text-grey">
                    Generate a top-down blueprint image from the Gaussian splat.
                </div>
            </div>
            <q-toggle v-model="config.enabled" label="Enable" color="primary" />
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <!-- Resolution Settings -->
            <div class="text-subtitle2" :class="isEnabled ? 'text-primary' : 'text-grey-7'">
                Output Resolution
            </div>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.imageWidth"
                        type="number"
                        label="Width"
                        suffix="px"
                        outlined
                        dense
                        :disable="!isEnabled"
                        :rules="[(val) => val > 0 || 'Width must be greater than 0']"
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.imageHeight"
                        type="number"
                        label="Height"
                        suffix="px"
                        outlined
                        dense
                        :disable="!isEnabled"
                        :rules="[(val) => val > 0 || 'Height must be greater than 0']"
                    />
                </div>
            </div>

            <q-separator inset class="q-my-sm" />

            <!-- Radius Scale -->
            <div class="text-subtitle2" :class="isEnabled ? 'text-primary' : 'text-grey-7'">
                Boundaries
            </div>
            <q-input
                v-model.number="config.radiusScale"
                type="number"
                label="Radius Scale"
                hint="Blueprint boundaries with respect to camera path radius"
                outlined
                dense
                step="0.1"
                :disable="!isEnabled"
                :rules="[(val) => val > 0 || 'Radius scale must be greater than 0']"
            />

            <q-separator inset class="q-my-sm" />

            <!-- Vertical Clip -->
            <div class="text-subtitle2" :class="isEnabled ? 'text-primary' : 'text-grey-7'">
                Vertical Bounds
            </div>
            <div class="row items-center q-col-gutter-md">
                <div class="col-8">
                    <q-slider
                        v-model="config.verticalClip"
                        :min="0"
                        :max="2"
                        :step="0.1"
                        label
                        :color="isEnabled ? 'primary' : 'grey-5'"
                        :disable="!isEnabled"
                    />
                </div>
                <div class="col-4">
                    <q-input
                        v-model.number="config.verticalClip"
                        type="number"
                        outlined
                        dense
                        :min="0"
                        :max="2"
                        :step="0.1"
                        suffix="x"
                        :disable="!isEnabled"
                    />
                </div>
            </div>
            <p class="text-caption" :class="isEnabled ? 'text-grey-7' : 'text-grey-5'">
                Only keep elements within vertical bounds, scaled with respect to camera path radius
            </p>

            <q-separator inset class="q-my-sm" />

            <!-- Opacity Settings -->
            <div class="text-subtitle2" :class="isEnabled ? 'text-primary' : 'text-grey-7'">
                Opacity Settings
            </div>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-input
                        v-model.number="config.opacityShift"
                        type="number"
                        label="Opacity Shift"
                        outlined
                        dense
                        step="0.1"
                        :min="-5"
                        :max="5"
                        :disable="!isEnabled"
                    />
                </div>
                <div class="col-6">
                    <q-input
                        v-model.number="config.opacity"
                        type="number"
                        label="Opacity Multiplier"
                        outlined
                        dense
                        step="0.01"
                        :min="0"
                        :max="1"
                        :disable="!isEnabled"
                    />
                </div>
            </div>
        </q-card-section>

        <q-separator />

        <q-btn
            flat
            label="Reset to Defaults"
            color="grey-7"
            @click="resetToDefaults"
            :disable="!isEnabled"
        />
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
