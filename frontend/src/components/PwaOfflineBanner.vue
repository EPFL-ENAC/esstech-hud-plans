<template>
    <div v-if="offline" class="pwa-offline-banner bg-warning text-dark" role="status">
        <q-icon name="wifi_off" aria-hidden="true" class="q-mr-sm" />
        {{ t('pwa.offline') }}
    </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
const offline = ref(!navigator.onLine);
const update = () => {
    offline.value = !navigator.onLine;
};
window.addEventListener('online', update);
window.addEventListener('offline', update);
onBeforeUnmount(() => {
    window.removeEventListener('online', update);
    window.removeEventListener('offline', update);
});
</script>

<style scoped>
.pwa-offline-banner {
    position: fixed;
    bottom: calc(96px + env(safe-area-inset-bottom));
    left: max(16px, env(safe-area-inset-left));
    right: max(16px, env(safe-area-inset-right));
    width: fit-content;
    max-width: 540px;
    margin: auto;
    padding: 8px 16px;
    border-radius: 8px;
    z-index: 7000;
    pointer-events: none;
}
</style>
