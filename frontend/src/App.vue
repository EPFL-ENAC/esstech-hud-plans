<template>
    <router-view />
</template>

<script setup lang="ts">
import { cleanupStaleDownloads } from 'src/lib/utils/resumableDownload';

// Remove stale download part files and broken resume records at app start.
void cleanupStaleDownloads().catch(() => undefined);
</script>
