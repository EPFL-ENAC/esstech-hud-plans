<template>
    <q-btn
        v-if="isPwa && !standalone"
        flat
        no-caps
        color="primary"
        icon="install_mobile"
        :label="t('pwa.install')"
        :loading="prompting"
        @click="install"
    />
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { storeToRefs } from 'pinia';
import { useQuasar } from 'quasar';
import { useI18n } from 'vue-i18n';
import { usePwaInstallStore } from 'src/stores/pwaInstall';

const isPwa = process.env.MODE === 'pwa';
const pwaInstall = usePwaInstallStore();
const { standalone, canPrompt } = storeToRefs(pwaInstall);
const { t } = useI18n();
const $q = useQuasar();
const prompting = ref(false);

async function install(): Promise<void> {
    if (prompting.value) return;
    prompting.value = true;
    try {
        if (canPrompt.value && (await pwaInstall.promptInstall()) !== 'unavailable') return;
        const platform = $q.platform.is;
        const instructions =
            platform.ios || (platform.mac && navigator.maxTouchPoints > 1)
                ? 'pwa.installIos'
                : platform.mac && platform.safari
                  ? 'pwa.installSafari'
                  : 'pwa.installBrowser';
        $q.dialog({
            title: t('pwa.install'),
            message: t(instructions),
            ok: { label: t('common.close'), flat: true, noCaps: true },
        });
    } finally {
        prompting.value = false;
    }
}
</script>
