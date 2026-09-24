<template>
    <q-page-sticky expand position="top" class="page-header-sticky">
        <q-toolbar class="page-header q-px-md">
            <q-btn
                v-if="back"
                flat
                dense
                no-caps
                color="primary"
                icon="arrow_back"
                :label="t('common.back')"
                @click="router.back()"
            />
            <q-toolbar-title class="page-header-title text-weight-bold">
                <slot name="title">{{ title }}</slot>
            </q-toolbar-title>
            <slot />
        </q-toolbar>
    </q-page-sticky>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

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
    z-index: 1500;
}

.page-header {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e5ea;
}

.page-header-title {
    font-size: 18px;
}

/* All header action buttons (back button and slot buttons such as New
   Capture) share one size. */
.page-header :deep(.q-btn) {
    font-size: 16px;
}
</style>
