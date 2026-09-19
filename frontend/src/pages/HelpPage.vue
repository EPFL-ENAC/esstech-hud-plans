<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('more.help')" />

        <q-card flat bordered>
            <q-card-section class="text-grey-7">
                {{ t('more.helpPlaceholder') }}
            </q-card-section>
        </q-card>
    </q-page>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import PageHeader from 'src/components/PageHeader.vue';

const { t } = useI18n();
</script>
