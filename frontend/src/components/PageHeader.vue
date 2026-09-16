<template>
    <q-page-sticky expand position="top" class="page-header-sticky">
        <q-toolbar class="page-header q-px-md q-py-sm text-dark" role="banner">
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
            <q-toolbar-title tag="h1" class="text-h4 text-weight-medium q-my-none">
                {{ title }}
            </q-toolbar-title>
            <div v-if="$slots.rightActions" class="row items-center no-wrap q-gutter-sm">
                <slot name="rightActions" />
            </div>
        </q-toolbar>
    </q-page-sticky>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

withDefaults(
    defineProps<{
        title: string;
        back?: boolean;
    }>(),
    {
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
