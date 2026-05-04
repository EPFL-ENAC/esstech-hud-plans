<script setup lang="ts" generic="T extends object">
import type { SplatPipelineStep } from 'src/stores/splats';
import LogPanel from './LogPanel.vue';
import type { LogParser } from 'src/lib/utils/logs';
import { ref, useTemplateRef } from 'vue';

const props = defineProps<{
    step: SplatPipelineStep<T>;
    parseLogCategory?: LogParser | undefined;
}>();

const showModal = ref(false);

const smallLogsContainerRef = useTemplateRef('smallLogsContainer');

defineExpose({
    scrollLogsToBottom: () => {
        smallLogsContainerRef.value?.scrollLogsToBottom();
    },
});
</script>

<template>
    <div>
        <log-panel
            ref="smallLogsContainer"
            :step="props.step"
            :parse-log-category="props.parseLogCategory"
        />

        <div class="q-pt-sm">
            <q-btn color="primary" icon="open_in_full" label="expand" @click="showModal = true" />
        </div>

        <q-dialog v-model="showModal" class="logs-modal">
            <q-card class="logs-modal-content">
                <q-card-section class="logs-main q-pb-none">
                    <log-panel
                        :step="props.step"
                        :parse-log-category="props.parseLogCategory"
                        max-height="80vh"
                    />
                </q-card-section>
                <q-card-actions align="right">
                    <q-btn color="red" @click="showModal = false">Close</q-btn>
                </q-card-actions>
            </q-card>
        </q-dialog>
    </div>
</template>

<style scoped>
.logs-modal .logs-modal-content {
    max-width: 95vw !important;
    max-height: 95vh !important;
    width: 95vw !important;
    height: 95vh !important;

    display: flex;
    flex-direction: column;
}

.logs-main {
    flex: 1;
}
</style>
