<template>
    <q-page class="q-pa-md" style="padding-top: 64px">
        <page-header :title="t('navigation.admin')" />
        <div class="wrapper">
            <div class="column items-start q-gutter-y-sm">
                <q-btn
                    size="lg"
                    color="primary"
                    label="Download parameters table"
                    icon="table_chart"
                    :href="downloadUrl"
                />
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { useI18n } from 'vue-i18n';
import { computed } from 'vue';
import { baseUrl } from 'boot/api';

const { t } = useI18n();

const downloadUrl = computed(() => {
    return `${baseUrl}/admin/parameters-table`; // directly returns the xlsx
});
</script>

<style scoped>
.wrapper {
    max-width: 600px;
    margin: 0 auto;
}
</style>
