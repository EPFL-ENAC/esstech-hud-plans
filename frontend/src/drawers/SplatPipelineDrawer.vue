<script setup lang="ts">
import { useRoute } from 'vue-router';
import { computed } from 'vue';
import { makeAsyncResultLoader, useReactiveChain } from 'unwrapped/vue';
import type { ErrorBase } from 'unwrapped/core';
import { type SplatPipelineStatus, useSplatStore } from 'src/stores/splats';
import SplatPipelineProgress from 'src/components/SplatPipelineProgress.vue';

const route = useRoute();
const generationId = computed(() => route.params.id as string);
const splatStore = useSplatStore();

const status = useReactiveChain(generationId, () => splatStore.getStatus(generationId.value));

const StatusLoader = makeAsyncResultLoader<SplatPipelineStatus, ErrorBase, SplatPipelineStatus>({});
</script>

<template>
    <div class="fit">
        <div class="q-pa-md">
            <h2>Pipeline status</h2>
            <div class="text-subtitle1">
                Job #{{ generationId }}
                <span
                    v-if="
                        status.unwrapOrNull()?.root_job_name &&
                        status.unwrapOrNull()?.root_job_name !== generationId
                    "
                    class="text-grey-6"
                >
                    (from #{{ status.unwrapOrNull()?.root_job_name }})
                </span>
            </div>
        </div>
        <div class="q-my-md">
            <StatusLoader :result="status">
                <template v-slot="{ value }">
                    <splat-pipeline-progress :value="value" />
                </template>
                <template v-slot:loading="{ progress }">
                    <splat-pipeline-progress v-if="progress" :value="progress" />
                    <h3 v-else class="q-ma-md">Pending...</h3>
                </template>
                <template v-slot:error="{ error }">
                    <h3>Error while getting status !</h3>
                    <pre>{{ JSON.stringify(error, undefined, 4) }}</pre>
                </template>
            </StatusLoader>
        </div>
    </div>
</template>

<style scoped>
h2 {
    font-size: 3rem;
    margin: 0 0 0.5rem 0;
}
</style>
