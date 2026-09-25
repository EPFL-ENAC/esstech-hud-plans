import { defineStore, skipHydrate } from 'pinia';
import { computed, onScopeDispose, ref, shallowRef } from 'vue';

type InstallResult = 'accepted' | 'dismissed' | 'unavailable';

interface InstallPromptEvent extends Event {
    prompt(): Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

function isNavigatorStandalone(): boolean {
    return (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export const usePwaInstallStore = defineStore('pwaInstall', () => {
    const standalone = ref(false);
    // A native event belongs to this browser session and must not be hydrated.
    const pendingInstallPrompt = skipHydrate(shallowRef<InstallPromptEvent | null>(null));
    const canPrompt = computed(() => !standalone.value && pendingInstallPrompt.value !== null);
    let removeListeners: (() => void) | null = null;

    // Capture the prompt at boot, before Login or More mounts. Repeated starts
    // share the same listeners, just as both pages share this store's state.
    function startTracking(): void {
        if (removeListeners) return;

        const displayMode = window.matchMedia('(display-mode: standalone)');
        const updateDisplayMode = () => {
            standalone.value = displayMode.matches || isNavigatorStandalone();
        };
        const onInstallAvailable = (event: Event) => {
            event.preventDefault();
            pendingInstallPrompt.value = event as InstallPromptEvent;
        };
        const onInstalled = () => {
            pendingInstallPrompt.value = null;
            updateDisplayMode();
        };

        updateDisplayMode();
        window.addEventListener('beforeinstallprompt', onInstallAvailable);
        window.addEventListener('appinstalled', onInstalled);
        window.addEventListener('pageshow', updateDisplayMode);
        displayMode.addEventListener('change', updateDisplayMode);

        removeListeners = () => {
            window.removeEventListener('beforeinstallprompt', onInstallAvailable);
            window.removeEventListener('appinstalled', onInstalled);
            window.removeEventListener('pageshow', updateDisplayMode);
            displayMode.removeEventListener('change', updateDisplayMode);
        };
    }

    function stopTracking(): void {
        removeListeners?.();
        removeListeners = null;
        pendingInstallPrompt.value = null;
    }

    async function promptInstall(): Promise<InstallResult> {
        const event = pendingInstallPrompt.value;
        if (!event || standalone.value) return 'unavailable';
        // Consume before awaiting: the native prompt is single-use.
        pendingInstallPrompt.value = null;
        try {
            await event.prompt();
            return (await event.userChoice).outcome;
        } catch {
            return 'unavailable';
        }
    }

    onScopeDispose(stopTracking);

    return {
        standalone,
        pendingInstallPrompt,
        canPrompt,
        startTracking,
        stopTracking,
        promptInstall,
    };
});
