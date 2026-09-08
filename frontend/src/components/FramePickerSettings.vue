<script setup lang="ts">
import { type FramePickerConfig, makeDefaultFramePickerConfig } from 'src/lib/splats/framePicker';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

const config = defineModel<FramePickerConfig>({
    required: true,
    default: () => makeDefaultFramePickerConfig(),
});

const resetToDefaults = () => {
    config.value = makeDefaultFramePickerConfig();
};
</script>

<template>
    <q-card flat :bordered="!embedded" :class="embedded ? 'embedded-settings' : 'q-pa-md q-mb-md'">
        <q-card-section>
            <div class="row items-center no-wrap">
                <div class="col">
                    <div class="text-h6 text-weight-light">
                        {{ t('settings.framePicker.title') }}
                    </div>
                    <div class="text-caption text-grey">
                        {{ t('settings.framePicker.description') }}
                    </div>
                </div>
                <q-toggle
                    v-model="config.enabled"
                    :label="t('settings.framePicker.enabled')"
                    left-label
                />
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md" :class="{ 'opacity-50': !config.enabled }">
            <div class="text-subtitle2 text-primary">{{ t('settings.framePicker.selection') }}</div>
            <div class="row q-col-gutter-md">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.min_fps"
                        type="number"
                        min="1"
                        :label="t('settings.framePicker.minimumFps')"
                        :hint="t('settings.framePicker.minimumFpsHint')"
                        outlined
                        :dense="!embedded"
                        :disable="!config.enabled"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.distance_threshold"
                        type="number"
                        :label="t('settings.framePicker.distanceThreshold')"
                        :hint="t('settings.framePicker.distanceHint')"
                        outlined
                        :dense="!embedded"
                        min="0"
                        step="0.01"
                        :disable="!config.enabled"
                    />
                </div>
            </div>

            <q-separator inset class="q-my-sm" />

            <div class="text-subtitle2 text-primary">
                {{ t('settings.framePicker.motionBlur') }}
            </div>
            <q-toggle
                v-model="config.remove_outliers"
                :label="t('settings.framePicker.removeOutliers')"
                :disable="!config.enabled"
            />

            <q-input
                v-model.number="config.outlier_sharpness_ratio"
                type="number"
                min="0"
                max="1"
                step="0.05"
                :label="t('settings.framePicker.sharpnessRatio')"
                :hint="t('settings.framePicker.sharpnessHint')"
                outlined
                :dense="!embedded"
                :disable="!config.enabled || !config.remove_outliers"
            />
        </q-card-section>

        <q-separator />

        <q-btn
            flat
            no-caps
            :label="t('settings.framePicker.reset')"
            color="grey-7"
            @click="resetToDefaults"
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

.opacity-50 {
    opacity: 0.5;
    pointer-events: none;
}

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
