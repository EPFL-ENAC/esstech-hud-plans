<template>
    <div class="loading-overlay" role="status" aria-live="polite" :aria-label="message">
        <q-spinner color="primary" size="64px" aria-hidden="true" />
        <span>{{ message }}</span>
    </div>
</template>

<script setup lang="ts">
defineProps<{ message: string }>();
</script>

<style scoped>
.loading-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    justify-content: center;
    align-items: center;
    background-color: rgba(255, 255, 255, 0.8);
    z-index: 9999;
}
</style>
