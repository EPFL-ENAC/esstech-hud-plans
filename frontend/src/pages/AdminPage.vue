<template>
    <q-page class="q-pa-md">
        <div class="wrapper">
            <h1 class="text-h5 q-mb-lg">Admin</h1>

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
import { computed } from 'vue';
import { baseUrl } from 'boot/api';

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
