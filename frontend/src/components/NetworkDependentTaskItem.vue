<template>
    <q-item class="q-pa-md">
        <q-item-section>
            <q-item-label class="text-subtitle1 text-weight-medium">
                {{ task.label }}
            </q-item-label>
            <q-item-label caption role="status" aria-live="polite">
                {{ t(`tasks.status.${status}`) }}
            </q-item-label>
            <q-item-label caption>
                {{ t('tasks.attempts', { count: task.state.attempts }) }}
            </q-item-label>

            <p v-if="task.state.message" class="q-mt-sm q-mb-none task-message">
                {{ task.state.message }}
            </p>
            <p v-if="errorMessage" class="text-negative q-mt-sm q-mb-none task-message">
                {{ errorMessage }}
            </p>

            <q-linear-progress
                v-if="showProgress"
                class="q-mt-md"
                :value="progressFraction"
                :indeterminate="indeterminate"
                :aria-label="t('tasks.progress', { label: task.label })"
            />
            <q-item-label v-if="progress" caption class="q-mt-xs">
                <template v-if="progress.total !== null">
                    {{
                        t('tasks.progressValue', {
                            completed: progress.completed,
                            total: progress.total,
                        })
                    }}
                </template>
                <template v-else>{{ progress.completed }}</template>
            </q-item-label>

            <div class="row q-gutter-sm q-mt-sm">
                <q-btn
                    v-if="canRetry"
                    flat
                    no-caps
                    color="primary"
                    :label="t('common.retry')"
                    :aria-label="t('tasks.retryLabel', { label: task.label })"
                    :disable="retryDisabled"
                    @click="emit('retry', task.id)"
                />
                <q-btn
                    v-if="canCancel"
                    flat
                    no-caps
                    color="negative"
                    :label="t('common.cancel')"
                    :aria-label="t('tasks.cancelLabel', { label: task.label })"
                    :disable="interrupting"
                    @click="emit('cancel', task.id)"
                />
            </div>
        </q-item-section>
    </q-item>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { NetworkDependentTask } from 'src/lib/networkDependentTasks';

const props = withDefaults(
    defineProps<{
        task: NetworkDependentTask;
        retryDisabled?: boolean;
    }>(),
    { retryDisabled: false },
);

const emit = defineEmits<{
    retry: [id: string];
    cancel: [id: string];
}>();

const { t } = useI18n();
const status = computed(() => props.task.state.status);
const progress = computed(() => props.task.state.progress);
const canRetry = computed(
    () => status.value === 'waiting' || status.value === 'blocked' || status.value === 'failed',
);
const canCancel = computed(() => status.value !== 'completed' && status.value !== 'cancelled');
const interrupting = computed(() => status.value === 'pausing' || status.value === 'cancelling');

const errorMessage = computed(() => {
    const error = props.task.state.error;
    if (error || status.value === 'failed' || status.value === 'blocked') {
        return error || t('tasks.unknownError');
    }
    return null;
});

const showProgress = computed(() => progress.value !== null || status.value === 'running');
const hasProgressTotal = computed(() => {
    const value = progress.value;
    return value !== null && value.total !== null && value.total > 0;
});
const indeterminate = computed(() => status.value === 'running' && !hasProgressTotal.value);
const progressFraction = computed(() => {
    const value = progress.value;
    if (value === null || value.total === null || value.total <= 0) return 0;
    return Math.min(1, Math.max(0, value.completed / value.total));
});
</script>

<style scoped>
.task-message {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
</style>
