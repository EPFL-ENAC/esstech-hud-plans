<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="row items-center justify-center">
                <div class="column items-center q-gutter-y-md">
                    <q-avatar rounded size="96px" color="primary" text-color="white">
                        <q-icon name="camera_indoor" />
                    </q-avatar>
                    <h1 class="text-h4 text-bold q-ma-none q-mt-lg">{{ t('auth.appTitle') }}</h1>
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
                    <pwa-install-button />
                    <div class="q-mt-xl login-language">
                        <language-selector />
                    </div>
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import LanguageSelector from 'src/components/LanguageSelector.vue';
import PwaInstallButton from 'src/components/PwaInstallButton.vue';
import { buildKeycloakLoginUrl } from 'src/lib/auth';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

function signIn() {
    window.location.href = buildKeycloakLoginUrl();
}
</script>

<style scoped>
.login-language {
    width: 200px;
}

@media (max-width: 599px) {
    .login-language {
        position: fixed;
        bottom: calc(16px + env(safe-area-inset-bottom));
        left: max(0px, env(safe-area-inset-left));
        right: max(0px, env(safe-area-inset-right));
        margin: 0 auto;
    }
}
</style>
