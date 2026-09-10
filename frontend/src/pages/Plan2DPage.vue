<template>
    <q-page
        class="bg-white text-dark q-px-md q-py-md"
        style="padding-top: 64px; display: flex; flex-direction: column"
        :aria-busy="isLoading"
    >
        <page-header :title="t('plans.building2dTitle')" />

        <div
            class="row justify-center q-gutter-x-xl q-py-sm q-mb-md"
            style="border-bottom: 1px solid #e5e5ea"
        >
            <q-btn
                v-for="tool in tools"
                :key="tool.name"
                stack
                flat
                no-caps
                :color="activeTool === tool.name ? 'primary' : 'grey-7'"
                @click="activeTool = tool.name"
            >
                <q-icon :name="tool.icon" size="22px" />
                <span class="text-caption text-weight-medium">{{ tool.label }}</span>
            </q-btn>
        </div>

        <q-banner v-if="error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ t('plans.splat.unavailable') }}
            <template #action>
                <q-btn flat :label="t('common.retry')" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <splat-download-progress v-if="isLoading" class="q-mb-md" />

        <template v-if="showSplat && data">
            <div class="viewer-wrapper">
                <interactive-blueprint-viewer
                    :splat-data="data"
                    :fetch-geometry="
                        () => fetchReconstructionBlueprintGeometryJSON(buildingId, reconstructionId)
                    "
                    :params="DEFAULT_BLUEPRINT_PARAMS"
                    fill
                />
            </div>
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionSplatQuery } from 'src/queries/reconstructions';
import { fetchReconstructionBlueprintGeometryJSON } from 'src/lib/maths/blueprintGeometry';
import { DEFAULT_BLUEPRINT_PARAMS } from 'src/lib/blueprintParams';
import SplatDownloadProgress from 'src/components/SplatDownloadProgress.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const InteractiveBlueprintViewer = defineAsyncComponent(
    () => import('src/components/InteractiveBlueprintViewer.vue'),
);

const route = useRoute();
const buildingId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''));
const reconstructionId = computed(() =>
    typeof route.query.reconstruction === 'string' ? route.query.reconstruction : '',
);
const { data, error, isLoading, refetch } = useReconstructionSplatQuery(
    buildingId,
    reconstructionId,
);
const showSplat = computed(
    () =>
        data.value !== undefined &&
        reconstructionId.value !== '' &&
        !(error.value instanceof ApiError && [401, 403, 404].includes(error.value.status)),
);

const activeTool = ref('measure');
const tools = computed(() => [
    { name: 'measure', label: t('plans.measure'), icon: 'straighten' },
    { name: 'slice', label: t('plans.slice'), icon: 'content_cut' },
    { name: 'note', label: t('plans.note'), icon: 'notes' },
]);
</script>

<style scoped>
.viewer-wrapper {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
}
</style>
