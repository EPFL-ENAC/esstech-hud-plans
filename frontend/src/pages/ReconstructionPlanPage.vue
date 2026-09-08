<template>
    <q-page
        class="bg-white text-dark q-px-md q-pb-xl"
        style="padding-top: 64px"
        :aria-busy="isLoading || (showSplat && rendering)"
    >
        <page-header title="3D Plan" />
        <h1 class="text-h6 text-weight-bold q-mt-none">
            Reconstruction {{ reconstructionId.slice(0, 8) }}
        </h1>

        <q-banner v-if="error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>

        <div v-if="isLoading" class="row items-center q-gutter-sm q-mb-md" role="status">
            <q-spinner color="primary" />
            <span>{{ data ? 'Refreshing splat…' : 'Loading splat…' }}</span>
        </div>

        <template v-if="showSplat && data">
            <q-banner v-if="renderError" class="bg-red-1 text-negative q-mb-md" role="alert">
                Unable to display this splat. The file may be invalid or 3D rendering unavailable in
                your browser.
                <template #action>
                    <q-btn flat label="Retry" @click="retryRendering" />
                </template>
            </q-banner>
            <template v-else>
                <div v-if="rendering" class="row items-center q-gutter-sm q-mb-md" role="status">
                    <q-spinner color="primary" />
                    <span>Preparing splat…</span>
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
                    Drag to rotate · Scroll or pinch to zoom · Right-drag or use two fingers to pan
                </p>
            </template>
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import { ApiError } from 'src/lib/buildings';
import { useReconstructionSplatQuery } from 'src/queries/reconstructions';

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
        if (error.value.status === 404) return 'The splat is not available.';
        if (error.value.status === 401 || error.value.status === 403) {
            return 'Unable to access this splat. Please sign in again.';
        }
    }
    return data.value
        ? 'Could not refresh this splat. Please try again.'
        : 'Unable to load the splat. Please try again.';
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
</script>
