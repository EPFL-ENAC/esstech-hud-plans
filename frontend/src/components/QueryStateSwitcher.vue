<template>
    <div class="query-state-switcher" :aria-busy="isLoading">
        <div v-if="state.status === 'error'" role="alert">
            <slot name="error" :error="state.error" :retry="retry" :retrying="isLoading">
                <div class="query-error">
                    <span>{{ errorMessage ?? t('common.queryLoadFailed') }}</span>
                    <button v-if="retry" type="button" :disabled="isLoading" @click="retry()">
                        {{ t('common.retry') }}
                    </button>
                </div>
            </slot>
        </div>

        <div v-if="state.status === 'pending'" role="status" :aria-label="loadingText">
            <slot name="pending">
                <span class="query-loading">{{ loadingText }}</span>
            </slot>
        </div>

        <div v-if="isLoading && content && slots.refreshing" role="status">
            <slot name="refreshing" />
        </div>

        <!-- Keep cached content mounted through refreshes and refresh errors. -->
        <div v-if="content" class="query-content">
            <slot name="success" :data="content.data" :refreshing="isLoading" />
        </div>
    </div>
</template>

<script setup lang="ts" generic="TData, TError = Error">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { AsyncStatus, DataState } from '@pinia/colada';

const props = defineProps<{
    state: DataState<TData, TError>;
    asyncStatus: AsyncStatus;
    retry?: () => unknown;
    loadingMessage?: string;
    errorMessage?: string;
}>();

const slots = defineSlots<{
    pending?(): unknown;
    error?(props: {
        error: TError;
        retry: (() => unknown) | undefined;
        retrying: boolean;
    }): unknown;
    success(props: { data: TData; refreshing: boolean }): unknown;
    refreshing?(): unknown;
}>();

const { t } = useI18n();

const isLoading = computed(() => props.asyncStatus === 'loading');
const loadingText = computed(() => props.loadingMessage ?? t('common.queryLoading'));
const content = computed<{ data: TData } | null>(() => {
    const state = props.state;
    if (state.status === 'success') return { data: state.data };
    if (state.data !== undefined) return { data: state.data };
    return null;
});
</script>

<style scoped>
.query-state-switcher {
    display: grid;
    gap: 1rem;
    min-width: 0;
}

.query-content {
    min-width: 0;
}

.query-error {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.75rem;
    color: var(--q-negative);
    overflow-wrap: anywhere;
}

.query-error button {
    padding: 0.5rem 0.75rem;
    border: 1px solid currentColor;
    border-radius: 4px;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
}

.query-error button:disabled {
    opacity: 0.6;
    cursor: wait;
}

.query-loading {
    color: #616161;
}
</style>
