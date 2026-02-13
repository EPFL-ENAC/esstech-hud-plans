<script setup lang="ts">
import { useRoute } from 'vue-router';
import { computed, onMounted, ref } from 'vue';
import { makeAsyncResultLoader, useReactiveChain } from 'unwrapped/vue';
import type { ErrorBase } from 'unwrapped/core';
import SplatRenderer from '../components/SplatRenderer.vue';
import InteractiveBlueprintViewer from '../components/InteractiveBlueprintViewer.vue';
import {
  type SplatPipelineSettings,
  type SplatPipelineStatus,
  useSplatStore,
} from 'src/stores/splats';

const route = useRoute();
const generationId = computed(() => route.params.id as string);
const splatStore = useSplatStore();

const splat = useReactiveChain(generationId, () => splatStore.getSplat(generationId.value));

splat.value.debug('splat');

const SplatLoader = makeAsyncResultLoader<ArrayBuffer, ErrorBase, SplatPipelineStatus>({});

const directions = ['top'] as const;

// Store the last progress status to access steps after completion
const pipelineStatus = ref<SplatPipelineStatus | null>(null);

// Store settings to check if blueprint was enabled
const settings = ref<SplatPipelineSettings | null>(null);
const settingsError = ref<string | null>(null);

// Fetch settings to determine if blueprint was enabled
async function fetchSettings(): Promise<void> {
  try {
    const response = await fetch(`http://localhost:8000/splats/settings/${generationId.value}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch settings: ${response.statusText}`);
    }
    settings.value = await response.json();
  } catch (e) {
    settingsError.value = e instanceof Error ? e.message : 'Unknown error';
  }
}

onMounted(async () => {
  await fetchSettings();
});
</script>

<template>
  <q-page class="">
    <SplatLoader :result="splat">
      <template v-slot="{ value }">
        <h3>Splat Viewer</h3>
        <splat-renderer :splat-data="value" />

        <h3>Interactive Blueprint</h3>
        <interactive-blueprint-viewer
          :splat-data="value"
          :generation-id="generationId"
          class="q-mb-lg"
        />

        <template v-if="settings?.blueprint">
          <h3>Blueprints</h3>
          <div v-for="direction in directions" :key="direction">
            <div class="q-mb-md">
              <h4 class="q-mb-xs">{{ direction.toUpperCase() }}</h4>
              <img
                :src="`http://localhost:8000/splats/blueprints/${generationId}/${direction}`"
                :alt="`Blueprint view from the ${direction}`"
                style="max-width: 700px; border: 1px solid black"
              />
            </div>
          </div>
        </template>
      </template>
      <template v-slot:loading="{ progress }">
        <div class="loading-progress">
          <q-circular-progress indeterminate size="xl" />
          <div v-if="progress">
            {{ ((pipelineStatus = progress), '') }}
            <div v-for="stepEntry in Object.entries(progress.steps)" :key="stepEntry[0]">
              <strong>{{ stepEntry[0].toUpperCase() }}:</strong>
              <span>{{ stepEntry[1].status }} - {{ stepEntry[1].progress }}%</span>
            </div>
          </div>
        </div>
      </template>
      <template v-slot:error="{ error }">
        <h3>Error!</h3>
        <pre>{{ JSON.stringify(error, undefined, 4) }}</pre>
      </template>
    </SplatLoader>
  </q-page>
</template>

<style scoped>
.loading-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100svh;
  gap: 1rem;
}
</style>
