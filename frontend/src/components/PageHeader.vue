<template>
    <q-page-sticky expand position="top" class="page-header-sticky">
        <q-toolbar class="page-header">
            <q-btn
                v-if="back"
                flat
                dense
                no-caps
                color="primary"
                icon="arrow_back"
                label="Back"
                @click="router.back()"
            />
            <q-toolbar-title class="text-subtitle1 text-weight-medium">
                <slot name="title">{{ title }}</slot>
            </q-toolbar-title>
            <slot />
        </q-toolbar>
    </q-page-sticky>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';

withDefaults(
    defineProps<{
        title?: string;
        back?: boolean;
    }>(),
    {
        title: '',
        back: true,
    },
);

const router = useRouter();
</script>

<style scoped>
.page-header-sticky {
    z-index: 2000;
}

.page-header {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e5ea;
}
</style>
