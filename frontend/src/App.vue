<template>
    <router-view />
    <pwa-offline-banner />
</template>

<script setup lang="ts">
import PwaOfflineBanner from 'src/components/PwaOfflineBanner.vue';
import { cleanupStaleDownloads } from 'src/lib/utils/resumableDownload';

// Remove stale download part files and broken resume records at app start.
void cleanupStaleDownloads().catch(() => undefined);
</script>
