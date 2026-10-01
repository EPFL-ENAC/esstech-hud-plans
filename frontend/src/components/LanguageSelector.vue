<template>
    <q-select
        v-model="locale"
        :options="languageOptions"
        :label="t('more.language')"
        emit-value
        map-options
        outlined
        dense
    />
</template>

<script setup lang="ts">
import { watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { MessageLanguages } from 'src/i18n/instance';
import { saveLocale, type AppLocale } from 'src/lib/language';

const { t, locale } = useI18n({ useScope: 'global' });
const languageOptions = [
    { label: 'English', value: 'en' },
    { label: 'Français', value: 'fr' },
    { label: 'Español', value: 'es' },
] satisfies { label: string; value: MessageLanguages }[];

// Only an explicit selection is saved, so the browser-detected default keeps following the browser.
watch(locale, (value) => saveLocale(value as AppLocale));
</script>
