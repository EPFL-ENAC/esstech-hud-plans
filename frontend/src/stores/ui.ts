import { defineStore } from 'pinia';
import { ref } from 'vue';

/**
 * Names of the "real" tab pages that can sit underneath the right
 * detail drawer.
 */
export type BackgroundPageName = 'home' | 'library' | 'more';

export const useUiStore = defineStore('ui', () => {
    /**
     * The page BackgroundPage renders beneath the right detail drawer.
     * Capture selects Library when opening a submitted building.
     */
    const background = ref<BackgroundPageName>('home');
    const libraryTab = ref<'list' | 'map'>('list');
    const librarySearch = ref<string | null>(null);

    function setBackground(page: BackgroundPageName): void {
        background.value = page;
    }

    return { background, libraryTab, librarySearch, setBackground };
});
