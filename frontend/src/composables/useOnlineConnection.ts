import { onScopeDispose, readonly, ref } from 'vue';

interface OnlineConnectionOptions {
    onOnline?: () => void;
    onOffline?: () => void;
}

export function useOnlineConnection({ onOnline, onOffline }: OnlineConnectionOptions = {}) {
    const isOnline = ref(navigator.onLine);

    function update(): void {
        const online = navigator.onLine;
        if (online === isOnline.value) return;

        isOnline.value = online;

        if (online) {
            onOnline?.();
        } else {
            onOffline?.();
        }
    }

    window.addEventListener('online', update);
    window.addEventListener('offline', update);

    onScopeDispose(() => {
        window.removeEventListener('online', update);
        window.removeEventListener('offline', update);
    });

    return { isOnline: readonly(isOnline) };
}
