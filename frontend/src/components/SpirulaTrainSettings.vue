<script setup lang="ts">
import { computed } from 'vue';
import { type SpirulaTrainConfig, makeDefaultSpirulaTrainConfig } from '../lib/splats/spirula';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const qualityOptions = computed(() => [
    { value: 'low', label: t('settings.spirula.train.qualities.low') },
    { value: 'medium', label: t('settings.spirula.train.qualities.medium') },
    { value: 'high', label: t('settings.spirula.train.qualities.high') },
    { value: 'ultra', label: t('settings.spirula.train.qualities.ultra') },
]);
const primitiveOptions = computed(() => [
    {
        value: '3dgs',
        label: t('settings.spirula.train.primitives.3dgs.label'),
        desc: t('settings.spirula.train.primitives.3dgs.description'),
    },
    {
        value: 'mip',
        label: t('settings.spirula.train.primitives.mip.label'),
        desc: t('settings.spirula.train.primitives.mip.description'),
    },
]);

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

const config = defineModel<SpirulaTrainConfig>({
    required: true,
});

const resetDefaults = () => {
    config.value = makeDefaultSpirulaTrainConfig();
};
</script>

<template>
    <q-card flat :bordered="!embedded" :class="embedded ? 'embedded-settings' : 'q-pa-md q-mb-md'">
        <q-card-section>
            <div class="text-h6 text-weight-light">{{ t('settings.spirula.train.title') }}</div>
            <div class="text-caption text-grey">
                {{ t('settings.spirula.train.description') }}
            </div>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-y-md">
            <div class="row q-col-gutter-sm">
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.numIterations"
                        type="number"
                        :label="t('settings.spirula.train.numIterations')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-select
                        v-model="config.quality"
                        :options="qualityOptions"
                        :label="t('settings.spirula.train.quality')"
                        emit-value
                        map-options
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>

            <q-select
                v-model="config.primitive"
                :options="primitiveOptions"
                :label="t('settings.spirula.train.primitive')"
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
                        v-model.number="config.shDegree"
                        :min="0"
                        :max="3"
                        :step="1"
                        type="number"
                        outlined
                        :dense="!embedded"
                        :label="t('settings.spirula.train.shDegree')"
                    />
                </div>
                <div class="col-12 col-sm-6">
                    <q-input
                        v-model.number="config.capMax"
                        type="number"
                        :label="t('settings.spirula.train.capMax')"
                        :hint="t('settings.spirula.train.capMaxHint')"
                        outlined
                        :dense="!embedded"
                    />
                </div>
            </div>
        </q-card-section>

        <q-separator />

        <q-btn
            flat
            no-caps
            :label="t('settings.spirula.train.reset')"
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
