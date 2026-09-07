<template>
    <component :is="pageComponent" />
</template>

<script setup lang="ts">
import { computed } from 'vue';
import HomePage from 'src/pages/HomePage.vue';
import CapturePage from 'src/pages/CapturePage.vue';
import LibraryPage from 'src/pages/LibraryPage.vue';
import MorePage from 'src/pages/MorePage.vue';
import { useUiStore, type BackgroundPageName } from 'src/stores/ui';

const ui = useUiStore();

const pages: Record<BackgroundPageName, unknown> = {
    home: HomePage,
    capture: CapturePage,
    library: LibraryPage,
    more: MorePage,
};

const pageComponent = computed(() => pages[ui.background] ?? HomePage);
</script>
