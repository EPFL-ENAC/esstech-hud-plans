<template>
    <q-page
        class="bg-white text-dark q-px-md q-pb-xl"
        style="padding-top: 64px"
        :aria-busy="isLoading || (showSplat && rendering)"
    >
        <page-header :title="t('plans.threeDimensional')" />
        <h1 class="text-h6 text-weight-bold q-mt-none">
            {{ t('reconstructions.named', { id: reconstructionId.slice(0, 8) }) }}
        </h1>

        <q-banner v-if="error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat :label="t('common.retry')" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <div v-if="isLoading" class="row items-center q-gutter-sm q-mb-md" role="status">
            <q-spinner color="primary" />
            <span>{{ data ? t('plans.splat.refreshing') : t('plans.splat.loading') }}</span>
        </div>

        <template v-if="showSplat && data">
            <q-banner v-if="renderError" class="bg-red-1 text-negative q-mb-md" role="alert">
                {{ t('plans.splat.displayFailed') }}
                <template #action>
                    <q-btn flat :label="t('common.retry')" @click="retryRendering" />
                </template>
            </q-banner>
            <template v-else>
                <div v-if="rendering" class="row items-center q-gutter-sm q-mb-md" role="status">
                    <q-spinner color="primary" />
                    <span>{{ t('plans.splat.preparing') }}</span>
                </div>
                <q-card flat bordered class="overflow-hidden">
                    <SplatRenderer
                        :key="`${buildingId}/${reconstructionId}/${renderAttempt}`"
                        :splat-data="data"
                        @ready="rendering = false"
                        @error="onRenderError"
                    />
                </q-card>
                <p class="text-caption text-grey-7 q-mt-sm">
                    {{ t('plans.splat.controls') }}
                </p>
            </template>
        </template>
        <template v-if="showSplat && data">
            <q-btn
                :label="t('plans.splat.downloadPly')"
                color="primary"
                icon="file_download"
                class="full-width q-mt-md"
                unelevated
                no-caps
                @click="downloadPly(data)"
            />
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionSplatQuery } from 'src/queries/reconstructions';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const SplatRenderer = defineAsyncComponent(() => import('src/components/SplatRenderer.vue'));
const route = useRoute();
const buildingId = computed(() =>
    typeof route.params.buildingId === 'string' ? route.params.buildingId : '',
);
const reconstructionId = computed(() =>
    typeof route.params.reconstructionId === 'string' ? route.params.reconstructionId : '',
);
const { data, error, isLoading, refetch } = useReconstructionSplatQuery(
    buildingId,
    reconstructionId,
);
const rendering = ref(true);
const renderError = ref(false);
const renderAttempt = ref(0);
const showSplat = computed(
    () =>
        data.value !== undefined &&
        !(error.value instanceof ApiError && [401, 403, 404].includes(error.value.status)),
);
const errorMessage = computed(() => {
    if (error.value instanceof ApiError) {
        if (error.value.status === 404) return t('plans.splat.unavailable');
        if (error.value.status === 401 || error.value.status === 403) {
            return t('plans.splat.accessDenied');
        }
    }
    return data.value ? t('plans.splat.refreshFailed') : t('plans.splat.loadFailed');
});

function retryRendering(): void {
    renderError.value = false;
    rendering.value = true;
    renderAttempt.value += 1;
}

function onRenderError(): void {
    renderError.value = true;
    rendering.value = false;
}

watch([buildingId, reconstructionId, data], retryRendering);

function downloadPly(splatData: ArrayBuffer): void {
    const blob = new Blob([splatData]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `reconstruction-${reconstructionId.value.slice(0, 8)}.ply`;
    a.click();
    URL.revokeObjectURL(url);
}
</script>
