<script setup lang="ts">
import { watch } from 'vue';
import {
    type ColmapConfig,
    makeAutoDefaults,
    makeManualDefaults,
    dataTypes,
    qualityOptions,
    cameraModels,
} from '../lib/splats/colmap';

const config = defineModel<ColmapConfig>({
    required: true,
});

const activeTab = defineModel<'auto' | 'manual'>('tab', {
    default: 'auto',
});

watch(
    activeTab,
    (newTab) => {
        config.value = newTab === 'auto' ? makeAutoDefaults() : makeManualDefaults();
    },
    { immediate: true },
);
</script>

<template>
    <q-card flat bordered class="q-pa-md q-mb-md">
        <q-card-section>
            <div class="text-h6 text-weight-light">COLMAP Camera Pose Estimation</div>
            <div class="text-caption text-grey">
                Estimate relative camera positions from image frames.
            </div>
        </q-card-section>

        <q-separator />

        <q-tabs
            v-model="activeTab"
            dense
            class="text-grey"
            active-color="primary"
            indicator-color="primary"
            narrow-indicator
        >
            <q-tab name="auto" label="Automatic (Simple)" />
            <q-tab name="manual" label="Manual (Advanced)" />
        </q-tabs>

        <q-separator />

        <q-tab-panels v-model="activeTab" animated>
            <!-- AUTOMATIC RECONSTRUCTOR FORM -->
            <q-tab-panel name="auto">
                <div class="q-gutter-md" v-if="'quality' in config">
                    <div class="text-h6 text-weight-light">Automatic Reconstructor</div>

                    <q-select
                        v-model="config.data_type"
                        :options="dataTypes"
                        label="Data Type"
                        hint="Individual/Internet: exhaustive matching. Video: sequential matching."
                        emit-value
                        map-options
                        filled
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

                    <q-select
                        v-model="config.quality"
                        :options="qualityOptions"
                        label="Reconstruction Quality"
                        emit-value
                        map-options
                        filled
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

                    <q-select
                        v-model="config.camera_model"
                        :options="cameraModels"
                        label="Camera Model"
                        emit-value
                        map-options
                        filled
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

                    <q-input
                        v-model.number="config.max_image_size"
                        type="number"
                        label="Max Image Dimension (px)"
                        filled
                    />

                    <div class="row">
                        <div class="col-6">
                            <q-toggle
                                v-model="config.single_camera"
                                label="Shared Camera Intrinsic"
                            />
                        </div>
                        <div class="col-6">
                            <q-toggle
                                v-model="config.use_global_mapper"
                                label="Use global mapper"
                            />
                        </div>
                    </div>
                </div>
            </q-tab-panel>

            <!-- MANUAL PIPELINE FORM -->
            <q-tab-panel name="manual">
                <div class="q-gutter-md" v-if="'max_num_features' in config">
                    <div class="text-h6 text-weight-light">Manual Pipeline</div>

                    <div class="text-subtitle2 text-primary">1. Feature Extraction</div>

                    <q-select
                        v-model="config.camera_model"
                        :options="cameraModels"
                        label="Camera Model"
                        emit-value
                        map-options
                        filled
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

                    <q-input
                        v-model.number="config.max_num_features"
                        type="number"
                        label="Max Features"
                        dense
                        outlined
                    />

                    <div class="text-subtitle2 text-primary">2. Sequential Matching</div>
                    <q-input
                        v-model.number="config.overlap"
                        type="number"
                        label="Frame Overlap"
                        dense
                        outlined
                    />

                    <q-toggle v-model="config.loop_closure" label="Loop Closure" />

                    <div class="text-subtitle2 text-primary">3. Mapper Settings</div>
                    <q-input
                        v-model.number="config.min_track_len"
                        type="number"
                        label="Min Track Length"
                        dense
                        outlined
                    />
                </div>
            </q-tab-panel>
        </q-tab-panels>
    </q-card>
</template>
