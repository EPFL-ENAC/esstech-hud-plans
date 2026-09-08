<script setup lang="ts">
import { computed } from 'vue';
import { type BrushTrainingConfig, makeDefaultBrushConfig } from '../lib/splats/brush';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const renderModeOptions = computed(() => [
    {
        value: 'default',
        label: t('settings.brush.renderModes.default.label'),
        desc: t('settings.brush.renderModes.default.description'),
    },
    {
        value: 'mip',
        label: t('settings.brush.renderModes.mip.label'),
        desc: t('settings.brush.renderModes.mip.description'),
    },
]);
const alphaModeOptions = computed(() => [
    {
        value: 'transparent',
        label: t('settings.brush.alphaModes.transparent.label'),
        desc: t('settings.brush.alphaModes.transparent.description'),
    },
    {
        value: 'masked',
        label: t('settings.brush.alphaModes.masked.label'),
        desc: t('settings.brush.alphaModes.masked.description'),
    },
]);

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
            <div class="text-h6 text-weight-light">{{ t('settings.brush.title') }}</div>
            <div class="text-caption text-grey">
                {{ t('settings.brush.description') }}
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <!-- Training Core -->
            <div class="text-subtitle2 text-primary">{{ t('settings.brush.coreTraining') }}</div>
            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.totalSteps"
                        type="number"
                        :label="t('settings.brush.totalSteps')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-select
                        v-model="config.renderMode"
                        :options="renderModeOptions"
                        :label="t('settings.brush.renderMode')"
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
                :label="t('settings.brush.shDegree')"
                class="q-mt-lg"
            />

            <!-- Refinement -->
            <q-separator />
            <div class="text-subtitle2 text-primary">{{ t('settings.brush.refinement') }}</div>

            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.maxSplats"
                        type="number"
                        :label="t('settings.brush.maxSplats')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.growthGradThreshold"
                        type="number"
                        step="0.001"
                        :label="t('settings.brush.growthThreshold')"
                        :hint="t('settings.brush.growthHint')"
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
                        :label="t('settings.brush.refineEvery')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.growthStopIter"
                        type="number"
                        :label="t('settings.brush.stopGrowth')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <q-separator />
            <div class="text-subtitle2 text-primary">{{ t('settings.brush.dataset') }}</div>

            <q-select
                v-model="config.alphaMode"
                :options="alphaModeOptions"
                :label="t('settings.brush.alphaMode')"
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
                        :label="t('settings.brush.maxResolution')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.subsampleFrames"
                        type="number"
                        :label="t('settings.brush.subsampleFrames')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <q-separator />
            <div class="text-subtitle2 text-primary">{{ t('settings.brush.exports') }}</div>

            <q-input
                v-model.number="config.exportEvery"
                type="number"
                min="1"
                :label="t('settings.brush.exportEvery')"
                outlined
                :dense="!embedded"
            />
        </q-card-section>

        <q-separator />

        <q-btn
            flat
            no-caps
            :label="t('settings.brush.reset')"
            color="grey"
            @click="resetDefaults"
        />
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
