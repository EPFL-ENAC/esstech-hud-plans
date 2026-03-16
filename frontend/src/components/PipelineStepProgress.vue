<script setup lang="ts" generic="T extends object">
import type { SplatPipelineStep } from 'src/stores/splats';
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue';
import { copyToClipboard, useQuasar } from 'quasar';

const props = defineProps<{
    step: SplatPipelineStep<T>;
    title: string;
}>();

const $q = useQuasar();
const logsContainerRef = useTemplateRef<HTMLDivElement>('logsContainer');

const commandString = computed(() => {
    if (Array.isArray(props.step.command)) {
        return props.step.command.join(' ');
    }
    return props.step.command;
});

const logString = computed(() => props.step.logs.join('\n'));

const statusColor = computed(() => {
    switch (props.step.status) {
        case 'completed':
            return 'positive';
        case 'failed':
            return 'negative';
        case 'running':
            return 'primary';
        default:
            return 'grey';
    }
});

async function scrollLogsToBottom() {
    const el = logsContainerRef.value;
    if (!el) return;

    await nextTick();
    el.scrollTo({
        top: el.scrollHeight,
        behavior: 'smooth',
    });
}

// Watch for new logs
watch(
    () => props.step.logs,
    async () => {
        const el = logsContainerRef.value;
        if (!el) return;

        // Check if user is near the bottom (within 20px) before the DOM updates
        const isAtBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 20;

        if (isAtBottom) {
            await scrollLogsToBottom();
        }
    },
    { deep: true },
);

async function copyText(text: string, label: string) {
    try {
        await copyToClipboard(text);
        $q.notify({
            message: `${label} copied to clipboard`,
            color: 'positive',
            icon: 'content_copy',
            timeout: 2000,
        });
    } catch (e) {
        console.error('Failed to copy text:', e);
        $q.notify({
            message: 'Failed to copy',
            color: 'negative',
        });
    }
}

function formatTimestamp(timestamp: string | null | undefined): string {
    if (!timestamp) {
        return 'N/A';
    }
    const formatter = new Intl.DateTimeFormat(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
    const date = new Date(timestamp);
    return formatter.format(date);
}

const wrapLogs = ref(false);
</script>

<template>
    <q-expansion-item
        expand-separator
        :label="title"
        :caption="`Status: ${step.status}`"
        :header-class="`text-${statusColor}`"
        @after-show="() => scrollLogsToBottom()"
    >
        <div class="q-pa-md q-gutter-y-sm">
            <!-- Settings Section -->
            <div v-if="step.settings && Object.keys(step.settings).length > 0" class="q-mb-md">
                <div class="text-subtitle2 q-mb-xs">Settings:</div>
                <pre class="bg-grey-2 q-pa-sm rounded-borders">{{
                    JSON.stringify(step.settings, null, 2)
                }}</pre>
            </div>

            <!-- Status and Progress Section -->
            <div class="row items-center q-col-gutter-md">
                <div class="col-grow">
                    <q-linear-progress
                        :value="step.progress"
                        :color="statusColor"
                        size="20px"
                        stripe
                        rounded
                    >
                        <div class="absolute-full flex flex-center">
                            <q-badge
                                color="white"
                                text-color="black"
                                :label="`${(step.progress * 100).toFixed(2)}%`"
                            />
                        </div>
                    </q-linear-progress>
                </div>
                <div class="col-auto text-caption">
                    Code: <strong>{{ step.return_code }}</strong>
                </div>
            </div>

            <!-- Timestamps -->
            <div class="row q-gutter-x-md text-caption text-grey-8">
                <div>Started: {{ formatTimestamp(step.started_at) }}</div>
                <div>Finished: {{ formatTimestamp(step.finished_at) }}</div>
            </div>

            <!-- Command Section -->
            <div v-if="step.command" class="relative-position q-mt-md">
                <div class="row items-center justify-between q-mb-xs">
                    <div class="text-subtitle2 q-mb-xs">Command:</div>
                    <q-btn
                        icon="content_copy"
                        label="Copy Command"
                        flat
                        dense
                        size="sm"
                        class="q-pa-sm"
                        @click="copyText(commandString, 'Command')"
                    />
                </div>
                <pre class="bg-grey-2 q-pa-sm rounded-borders scroll-x q-mt-xs">
                    {{ commandString.trim() }}
                </pre>
            </div>

            <!-- Logs Section -->
            <div class="relative-position q-mt-md">
                <div class="row items-center justify-between q-mb-xs">
                    <div class="text-subtitle2">Logs:</div>
                    <div class="row items-center q-gutter-x-sm">
                        <q-toggle
                            v-model="wrapLogs"
                            label="Line wrap"
                            size="xs"
                            dense
                            class="text-caption"
                        />
                        <q-btn
                            icon="content_copy"
                            label="Copy Logs"
                            flat
                            dense
                            size="sm"
                            class="q-pa-sm"
                            @click="copyText(logString, 'Logs')"
                        />
                    </div>
                </div>
                <div
                    ref="logsContainer"
                    :class="[
                        'logs-container bg-black text-white q-pa-sm rounded-borders',
                        { 'scroll-x': !wrapLogs },
                    ]"
                    :style="`--line-number-width: ${`${props.step.logs.length}`.length + 1}ch`"
                >
                    <div v-for="(line, index) in step.logs" :key="index" class="log-line">
                        <span class="line-number">{{ index + 1 }}</span>
                        <span>{{ line }}</span>
                    </div>
                </div>
            </div>
        </div>
    </q-expansion-item>
</template>

<style scoped>
.logs-container {
    max-height: 300px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-all;
}

.no-wrap-logs {
    white-space: pre !important;
    word-break: normal !important;
}

.scroll-x {
    overflow-x: auto;
    white-space: pre;
}

.log-line {
    padding: 0.25rem 0;
    display: grid;
    grid-template-columns: var(--line-number-width, 2ch) 1fr;
    gap: 0.5rem;
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
