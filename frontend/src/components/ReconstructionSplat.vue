<template>
    <section aria-label="Reconstruction splat" class="q-gutter-y-sm">
        <div class="row items-center justify-between">
            <div class="text-subtitle2">Splat</div>
            <q-btn v-if="splatData" flat dense label="Close splat" @click="reset" />
        </div>

        <div v-if="loading" role="status" class="row items-center q-gutter-sm">
            <q-spinner color="primary" size="24px" />
            <span>Loading splat…</span>
            <q-btn flat dense label="Cancel" @click="reset" />
        </div>

        <q-banner v-else-if="errorMessage" rounded class="bg-red-1 text-negative" role="alert">
            {{ errorMessage }}
            <template #action>
                <q-btn flat color="negative" label="Retry" @click="load" />
            </template>
        </q-banner>

        <div v-else-if="splatData" class="q-gutter-y-sm">
            <div v-if="rendering" role="status" class="row items-center q-gutter-sm">
                <q-spinner color="primary" size="24px" />
                <span>Preparing splat…</span>
            </div>
            <SplatRenderer
                :splat-data="splatData"
                @ready="rendering = false"
                @error="onRenderError"
            />
            <div class="text-caption text-grey-7">
                Drag to rotate · Scroll or pinch to zoom · Right-drag or use two fingers to pan
            </div>
        </div>

        <q-btn v-else outline color="primary" icon="view_in_ar" label="Load splat" @click="load" />
    </section>
</template>

<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { ApiError, getReconstructionSplat } from 'src/lib/buildings';

const SplatRenderer = defineAsyncComponent(() => import('src/components/SplatRenderer.vue'));
const props = defineProps<{
    buildingId: string;
    reconstructionId: string;
}>();

const splatData = shallowRef<ArrayBuffer | null>(null);
const loading = ref(false);
const rendering = ref(false);
const errorMessage = ref('');
let pendingRequest: AbortController | null = null;

function reset(): void {
    pendingRequest?.abort();
    pendingRequest = null;
    splatData.value = null;
    loading.value = false;
    rendering.value = false;
    errorMessage.value = '';
}

async function load(): Promise<void> {
    reset();
    const controller = new AbortController();
    pendingRequest = controller;
    loading.value = true;

    try {
        const data = await getReconstructionSplat(
            props.buildingId,
            props.reconstructionId,
            controller.signal,
        );
        if (!controller.signal.aborted) {
            rendering.value = true;
            splatData.value = data;
        }
    } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
            errorMessage.value = 'The splat is not available.';
        } else if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            errorMessage.value = 'Unable to access this splat. Please sign in again.';
        } else {
            errorMessage.value = 'Unable to load the splat. Please try again.';
        }
    } finally {
        if (pendingRequest === controller) {
            pendingRequest = null;
            loading.value = false;
        }
    }
}

function onRenderError(): void {
    reset();
    errorMessage.value =
        'Unable to display this splat. The file may be invalid or 3D rendering unavailable in your browser.';
}

watch(() => [props.buildingId, props.reconstructionId], reset);
onBeforeUnmount(reset);
</script>
