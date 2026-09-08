<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="row items-center justify-center">
                <div class="column items-center q-gutter-y-md">
                    <h1 class="text-h4 q-ma-none">{{ t('auth.appTitle') }}</h1>
                    <q-btn :label="t('auth.signIn')" color="primary" size="lg" @click="signIn" />
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import { buildKeycloakLoginUrl } from 'src/lib/auth';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

function signIn() {
    window.location.href = buildKeycloakLoginUrl();
}
</script>
