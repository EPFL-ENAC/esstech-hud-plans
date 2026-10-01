<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('more.settings')" />

        <section class="q-mb-xl">
            <h2 class="text-h6 text-weight-bold">{{ t('more.languageSettings') }}</h2>
            <language-selector />
        </section>
    </q-page>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import LanguageSelector from 'src/components/LanguageSelector.vue';
import PageHeader from 'src/components/PageHeader.vue';

const { t } = useI18n();
</script>
