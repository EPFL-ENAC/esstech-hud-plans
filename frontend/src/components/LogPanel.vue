<script setup lang="ts" generic="T extends object">
import type { SplatPipelineStep } from 'src/stores/splats';
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue';
import CopyButton from './CopyButton.vue';
import {
    LogProcessor,
    type ProcessedLog,
    type LogCategory,
    type LogParser,
} from 'src/lib/utils/logs';
import ScrollableContainer from './ScrollableContainer.vue';

const props = defineProps<{
    step: SplatPipelineStep<T>;
    maxHeight?: string;
    parseLogCategory?: LogParser | undefined;
}>();

const logsContainerRef = useTemplateRef<typeof ScrollableContainer>('logsContainer');
const wrapLogs = ref(false);

const processor = new LogProcessor(props.parseLogCategory);
const processedLogs = ref<ProcessedLog[]>(processor.update(props.step.logs));
const activeFilters = ref<Set<LogCategory>>(new Set(['info', 'warning', 'error']));

const existingCategories = computed(() => {
    const cats = new Set<LogCategory>();
    for (const log of processedLogs.value) {
        cats.add(log.category);
    }
    return cats;
});

const categoryCounts = computed(() => {
    const counts: Record<LogCategory, number> = {
        info: 0,
        warning: 0,
        error: 0,
    };
    for (const log of processedLogs.value) {
        counts[log.category]++;
    }
    return counts;
});

const showFilters = computed(() => existingCategories.value.size > 1);

const filteredLogs = computed(() => {
    return processedLogs.value.filter((log) => activeFilters.value.has(log.category));
});

const logString = computed(() => props.step.logs.join('\n'));

function getCategoryIcon(cat: LogCategory) {
    switch (cat) {
        case 'error':
            return 'error';
        case 'warning':
            return 'warning';
        default:
            return 'info';
    }
}

watch(
    () => props.step.logs,
    async (newRawLogs) => {
        const shouldAutoScroll = logsContainerRef.value?.isScrolledToBottom() ?? true;
        processedLogs.value = [...processor.update(newRawLogs)];

        await nextTick();
        if (shouldAutoScroll) {
            logsContainerRef.value?.scrollToBottom();
        }
    },
    { deep: true, immediate: true },
);

watch(
    () => activeFilters.value,
    async () => {
        const shouldAutoScroll = logsContainerRef.value?.isScrolledToBottom() ?? true;
        await nextTick();
        if (shouldAutoScroll) {
            logsContainerRef.value?.scrollToBottom();
        }
    },
    { deep: true, immediate: true },
);

function toggleFilter(cat: LogCategory) {
    const newFilters = new Set(activeFilters.value);
    if (newFilters.has(cat)) {
        newFilters.delete(cat);
    } else {
        newFilters.add(cat);
    }
    activeFilters.value = newFilters;
}
</script>

<template>
    <div class="row items-center justify-between q-mb-xs">
        <div class="text-subtitle2 text-weight-medium">Logs ({{ props.step.logs.length }}):</div>
        <div class="row items-center q-gutter-x-sm">
            <q-toggle v-model="wrapLogs" label="Line wrap" size="xs" dense class="text-caption" />
            <copy-button
                :get-text="() => logString"
                message="Logs copied to clipboard"
                label="Copy Logs"
                flat
                dense
                size="sm"
                class="q-pa-sm"
            />
        </div>
    </div>

    <div v-if="showFilters" class="row q-gutter-xs q-mb-sm">
        <q-chip
            v-for="cat in ['info', 'warning', 'error'] as const"
            v-show="existingCategories.has(cat)"
            :key="cat"
            :outline="!activeFilters.has(cat)"
            :color="cat === 'error' ? 'negative' : cat === 'warning' ? 'warning' : 'grey-9'"
            :icon="getCategoryIcon(cat)"
            text-color="white"
            size="sm"
            clickable
            @click="toggleFilter(cat)"
        >
            <span class="text-uppercase text-weight-bold q-mr-xs">{{ cat }}</span>
            <span>({{ categoryCounts[cat] }})</span>
        </q-chip>
    </div>

    <div
        class="relative-position"
        :style="`--line-number-width: ${`${props.step.logs.length}`.length + 1}ch; --max-height: ${props.maxHeight || `300px`}`"
    >
        <scrollable-container
            ref="logsContainer"
            :container-class="[
                'logs-container bg-black text-white q-pa-sm rounded-borders',
                { 'scroll-x': !wrapLogs },
            ]"
        >
            <div
                v-for="log in filteredLogs"
                :key="log.index"
                :class="['log-line', `log-line--${log.category}`]"
            >
                <span class="line-number">{{ log.index + 1 }}</span>
                <span class="log-content">{{ log.line }}</span>
            </div>

            <div
                v-if="filteredLogs.length === 0"
                class="text-grey-6 text-italic text-center q-pa-md"
            >
                No logs to show for selected filters
            </div>
        </scrollable-container>
    </div>
</template>

<style scoped>
:deep(.logs-container) {
    max-height: var(--max-height, 300px);
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-all;
}

:deep(.scroll-x) {
    overflow-x: auto;
    white-space: pre;
}

.log-line {
    padding: 0.1rem 0;
    display: grid;
    grid-template-columns: var(--line-number-width, 2ch) 1fr;
    gap: 0.5rem;
}

.log-line--warning {
    color: rgb(255, 200, 0);
}

.log-line--error {
    color: rgb(255, 50, 0);
}

.log-content {
    min-width: 0;
}

.line-number {
    display: block;
    text-align: right;
    color: #aaa;
    user-select: none;
}
</style>
