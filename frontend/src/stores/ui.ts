import { defineStore } from 'pinia';
import { ref } from 'vue';

/**
 * Names of the "real" tab pages that can sit underneath the right
 * detail drawer.
 */
export type BackgroundPageName = 'home' | 'capture' | 'library' | 'more';

export const useUiStore = defineStore('ui', () => {
    /**
     * The last real tab page the user visited. The right detail drawer keeps
     * this page mounted as its background, so opening a building from Home or
     * Library leaves the user on Home or Library.
     */
    const background = ref<BackgroundPageName>('home');
    const libraryTab = ref<'list' | 'map'>('list');

    function setBackground(page: BackgroundPageName) {
        background.value = page;
    }

    return { background, libraryTab, setBackground };
});
