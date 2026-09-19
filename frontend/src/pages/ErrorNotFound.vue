<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page
                class="bg-blue text-white text-center q-pa-md flex flex-center"
                style="padding-top: 64px"
            >
                <page-header :back="false" :title="t('notFound.message')" />
                <div>
                    <div style="font-size: 30vh">404</div>

                    <div class="text-h2" style="opacity: 0.4">{{ t('notFound.message') }}</div>

                    <q-btn
                        class="q-mt-xl"
                        color="white"
                        text-color="blue"
                        unelevated
                        to="/"
                        :label="t('notFound.goHome')"
                        no-caps
                    />
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
</script>
