<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="row items-center justify-center" style="padding-top: 64px">
                <page-header :back="false" :title="t('auth.appTitle')" />
                <div class="column items-center q-gutter-y-md">
                    <q-avatar rounded size="96px" color="primary" text-color="white">
                        <q-icon name="camera_indoor" />
                    </q-avatar>
                    <p class="text-subtitle1 text-grey-8 q-ma-none">
                        {{ t('auth.appDescription') }}
                    </p>
                    <q-btn
                        :label="t('auth.signIn')"
                        color="primary"
                        no-caps
                        unelevated
                        size="lg"
                        class="q-mt-xl"
                        @click="signIn"
                    />
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { buildKeycloakLoginUrl } from 'src/lib/auth';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

function signIn() {
    window.location.href = buildKeycloakLoginUrl();
}
</script>
