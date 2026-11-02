<template>
    <nav
        v-if="(query.state.value.data?.total ?? 0) > 0 || offset > 0"
        :aria-label="ariaLabel"
        class="row justify-center"
    >
        <q-pagination
            v-model="page"
            :max="totalPages"
            :max-pages="5"
            :boundary-numbers="false"
            :ellipses="false"
            direction-links
            color="primary"
            :disable="disabled"
        />
    </nav>
</template>

<script setup lang="ts" generic="TItem, TError = Error">
import type { UseQueryReturn } from '@pinia/colada';
import { computed, watch } from 'vue';
import type { Page } from 'src/lib/pagination';

type PaginationQuery<T, E> = Pick<UseQueryReturn<Page<T>, E>, 'state' | 'asyncStatus' | 'refetch'>;

const offset = defineModel<number>('offset', { required: true });
const props = defineProps<{
    query: PaginationQuery<TItem, TError>;
    pageSize: number;
    disabled: boolean;
    ariaLabel: string;
}>();

// Keep the paginator's bounds while a different page is loading.
const totalPages = computed<number>((previous = 1) => {
    const data = props.query.state.value.data;
    return data === undefined || props.query.asyncStatus.value === 'loading'
        ? previous
        : Math.max(1, Math.ceil(data.total / props.pageSize));
});
const page = computed({
    get: () => offset.value / props.pageSize + 1,
    set: (value: number) => {
        offset.value = (value - 1) * props.pageSize;
    },
});

watch([() => props.query.state.value, () => props.query.asyncStatus.value], ([state, status]) => {
    if (state.status !== 'success' || status === 'loading') return;
    const lastOffset = (totalPages.value - 1) * props.pageSize;
    if (offset.value > lastOffset) {
        offset.value = lastOffset;
        void props.query.refetch();
    }
});
</script>
