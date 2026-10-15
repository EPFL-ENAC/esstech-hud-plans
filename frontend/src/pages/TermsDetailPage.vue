<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('terms.title')" />

        <div v-if="loading" class="row items-center justify-center q-pa-lg q-gutter-x-md">
            <q-spinner size="lg" color="primary" />
            <div>{{ t('terms.loading') }}</div>
        </div>
        <div v-else-if="error" class="q-pa-md text-negative">{{ error }}</div>
        <div v-else class="q-pa-md">
            <div class="terms-content" v-html="renderedTerms"></div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { authFetch } from 'src/lib/auth';
import MarkdownIt from 'markdown-it';
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { baseUrl } from 'boot/api';

const { t, locale } = useI18n();
const md = new MarkdownIt();

const loading = ref(true);
const error = ref('');
const content = ref<Record<string, string> | null>(null);

const termsLocale = computed(() => locale.value.split('-')[0] ?? 'en');
const renderedTerms = computed(() => {
    // The terms locale files ship for en/fr/es; fall back to English.
    const markdown = content.value?.[termsLocale.value] ?? content.value?.en;
    return markdown !== undefined ? md.render(markdown) : '';
});

onMounted(async () => {
    try {
        const response = await authFetch(`${baseUrl}/terms`);
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const data = (await response.json()) as { content: Record<string, string> };
        content.value = data.content;
    } catch {
        error.value = t('terms.loadFailed');
    } finally {
        loading.value = false;
    }
});
</script>

<style scoped>
.terms-content {
    max-width: 720px;
    margin: 0 auto;
}
</style>
