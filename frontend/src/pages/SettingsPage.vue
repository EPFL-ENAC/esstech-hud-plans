<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('more.settings')" />

        <section class="q-mb-xl">
            <h2 class="text-h5">{{ t('more.languageSettings') }}</h2>
            <q-select
                v-model="locale"
                :options="languageOptions"
                :label="t('more.language')"
                emit-value
                map-options
                outlined
                dense
            />
        </section>
    </q-page>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import PageHeader from 'src/components/PageHeader.vue';
import type { MessageLanguages } from 'src/i18n/instance';

const { t, locale } = useI18n({ useScope: 'global' });
const languageOptions = [
    { label: 'English', value: 'en' },
    { label: 'Français', value: 'fr' },
    { label: 'Español', value: 'es' },
] satisfies { label: string; value: MessageLanguages }[];
</script>
