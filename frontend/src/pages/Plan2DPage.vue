<template>
    <q-page
        class="bg-white text-dark q-px-md q-py-md"
        style="padding-top: 64px; display: flex; flex-direction: column"
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

        <QueryStateSwitcher
            v-if="reconstructionId"
            class="splat-query"
            :state="state"
            :async-status="asyncStatus"
            :retry="refetch"
            :loading-message="t('plans.splat.loading')"
            :error-message="t('plans.splat.unavailable')"
        >
            <template #pending>
                <splat-download-progress role="presentation" />
            </template>
            <template #refreshing>
                <splat-download-progress role="presentation" />
            </template>
            <template #success="{ data }">
                <template v-if="showSplat">
                    <div class="viewer-wrapper">
                        <interactive-blueprint-viewer
                            :splat-data="data"
                            :fetch-geometry="
                                () =>
                                    fetchReconstructionBlueprintGeometryJSON(
                                        buildingId,
                                        reconstructionId,
                                    )
                            "
                            :params="DEFAULT_BLUEPRINT_PARAMS"
                            fill
                        />
                    </div>
                </template>
            </template>
        </QueryStateSwitcher>
    </q-page>
</template>

<script setup lang="ts">
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
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
const { data, error, state, asyncStatus, refetch } = useReconstructionSplatQuery(
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
.splat-query {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
}

.splat-query :deep(.query-content) {
    display: flex;
    flex: 1;
    min-height: 0;
}

.viewer-wrapper {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
}
</style>
