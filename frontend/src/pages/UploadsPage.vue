<template>
    <q-page class="bg-white text-dark q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('uploads.title')">
            <q-btn
                flat
                no-caps
                color="primary"
                icon="add"
                :label="$q.screen.lt.sm ? undefined : t('uploads.new.title')"
                :aria-label="t('uploads.new.title')"
                :to="{ name: 'new-upload' }"
            />
            <q-btn
                flat
                no-caps
                color="primary"
                icon="videocam"
                :label="$q.screen.lt.sm ? undefined : t('uploads.record.action')"
                :aria-label="t('uploads.record.action')"
                :to="{ name: 'record-upload' }"
            />
            <q-btn
                flat
                no-caps
                color="primary"
                icon="refresh"
                :label="t('uploads.refresh')"
                :disable="uploadsList?.isLoading"
                @click="uploadsList?.refetch()"
            />
        </page-header>

        <my-uploads-list ref="uploadsList" />
    </q-page>
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import PageHeader from 'src/components/PageHeader.vue';
import MyUploadsList from 'src/components/MyUploadsList.vue';

const { t } = useI18n();
const uploadsList = useTemplateRef<InstanceType<typeof MyUploadsList>>('uploadsList');
</script>
