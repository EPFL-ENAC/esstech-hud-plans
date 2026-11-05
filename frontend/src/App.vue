<template>
    <router-view />
    <pwa-offline-banner />
</template>

<script setup lang="ts">
import PwaOfflineBanner from 'src/components/PwaOfflineBanner.vue';
</script>
