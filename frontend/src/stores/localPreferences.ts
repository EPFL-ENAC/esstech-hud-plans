import { defineStore } from 'pinia';
import { ref, watch } from 'vue';

const hideVideoTipsStorageKey = 'hud-hide-video-tips';

export const useLocalPreferencesStore = defineStore('localPreferences', () => {
    const hideVideoTips = ref(false);

    try {
        hideVideoTips.value = localStorage.getItem(hideVideoTipsStorageKey) === 'true';
    } catch {
        // Keep the default when browser storage is unavailable.
    }

    watch(
        hideVideoTips,
        (value) => {
            try {
                localStorage.setItem(hideVideoTipsStorageKey, String(value));
            } catch {
                // The preference still applies for this session if it cannot be saved.
            }
        },
        { flush: 'sync' },
    );

    return { hideVideoTips };
});
