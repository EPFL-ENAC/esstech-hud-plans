<template>
    <q-page
        class="bg-white text-dark q-px-md q-py-md"
        style="padding-top: 64px; display: flex; flex-direction: column"
    >
        <page-header :title="t('plans.building2dTitle')" />

        <div
            class="row justify-center q-gutter-x-xl q-py-sm"
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
            :state="pointCloudQuery.state"
            :async-status="pointCloudQuery.asyncStatus"
            :retry="pointCloudQuery.refetch"
            :loading-message="t('plans.points.preparing')"
            :error-message="t('plans.splat.unavailable')"
        >
            <template #pending>
                <div class="text-caption text-grey-7 q-mb-xs">
                    {{ t('plans.points.preparing') }}
                </div>
                <splat-download-progress role="presentation" />
            </template>
            <template #refreshing>
                <splat-download-progress role="presentation" />
            </template>
            <template #success="{ data }">
                <div v-if="showPointCloud" class="viewer-wrapper">
                    <plan-point-cloud-viewer
                        :buffer="data.buffer"
                        :view-params="data.viewParams"
                        :reconstruction-id="reconstructionId"
                        fill
                    />
                </div>
            </template>
        </QueryStateSwitcher>
    </q-page>
</template>

<script setup lang="ts">
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import { computed, defineAsyncComponent, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionPointCloudQuery } from 'src/queries/reconstructions';
import SplatDownloadProgress from 'src/components/SplatDownloadProgress.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const PlanPointCloudViewer = defineAsyncComponent(
    () => import('src/components/PlanPointCloudViewer.vue'),
);

const route = useRoute();
const buildingId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''));
const reconstructionId = computed(() =>
    typeof route.query.reconstruction === 'string' ? route.query.reconstruction : '',
);
const pointCloudQuery = reactive(useReconstructionPointCloudQuery(buildingId, reconstructionId));

const showPointCloud = computed(
    () =>
        pointCloudQuery.data !== undefined &&
        reconstructionId.value !== '' &&
        !(
            pointCloudQuery.error instanceof ApiError &&
            [401, 403, 404].includes(pointCloudQuery.error.status)
        ),
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
    /* Cancel the page's q-px-md/q-py-md so the viewer is flush with the page
       edges on the sides and the bottom. Only the viewer bleeds: the loading
       and progress states keep the page padding. */
    margin: 0 -16px -16px;
}
</style>
