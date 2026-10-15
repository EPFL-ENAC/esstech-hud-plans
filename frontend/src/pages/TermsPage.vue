<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="column bg-white text-dark" style="padding-top: 64px">
                <page-header :back="false" :title="t('auth.appTitle')" />
                <div v-if="loading" class="col row items-center justify-center q-gutter-x-md">
                    <q-spinner size="lg" color="primary" />
                    <div>{{ t('terms.loading') }}</div>
                </div>
                <div v-else class="col scroll q-pa-md">
                    <div class="terms-content" v-html="renderedTerms"></div>
                </div>
            </q-page>
        </q-page-container>
        <q-footer class="bg-white text-dark">
            <q-banner v-if="error" rounded dense class="bg-red-1 text-negative">
                {{ error }}
            </q-banner>
            <div class="q-pa-md">
                <div class="terms-content row items-center no-wrap justify-between">
                    <q-btn flat color="negative" :label="t('terms.logout')" @click="onLogout" />
                    <div class="row items-center no-wrap justify-end q-gutter-x-sm footer-actions">
                        <language-selector class="footer-language" />
                        <q-btn
                            unelevated
                            color="primary"
                            :label="t('terms.accept')"
                            :disable="accepting"
                            @click="onAccept"
                        />
                    </div>
                </div>
            </div>
        </q-footer>
    </q-layout>
</template>

<script setup lang="ts">
import LanguageSelector from 'src/components/LanguageSelector.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { authFetch, getTermsAccepted, logout } from 'src/lib/auth';
import MarkdownIt from 'markdown-it';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { baseUrl } from 'boot/api';

const { t, locale } = useI18n();
const router = useRouter();
const md = new MarkdownIt();

const loading = ref(true);
const accepting = ref(false);
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
        const data = (await response.json()) as {
            version: string;
            content: Record<string, string>;
        };
        content.value = data.content;
    } catch {
        error.value = t('terms.loadFailed');
    } finally {
        loading.value = false;
    }
});

async function onAccept(): Promise<void> {
    accepting.value = true;
    try {
        const response = await authFetch(`${baseUrl}/terms/accept`, { method: 'POST' });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        // Refresh the guard cache so navigation away from /terms passes.
        await getTermsAccepted(true);
        await router.replace('/');
    } catch {
        error.value = t('terms.acceptFailed');
    } finally {
        accepting.value = false;
    }
}

function onLogout(): void {
    logout();
    void router.replace('/login');
}
</script>

<style scoped>
.terms-content {
    max-width: 720px;
    margin: 0 auto;
}

.footer-language {
    flex: 0 1 200px;
    min-width: 0;
}

/* Claim the free bar space so the 200px selector basis can resolve; the
   group shrinks on narrow screens and the selector follows. */
.footer-actions {
    flex: 1 1 auto;
}
</style>
