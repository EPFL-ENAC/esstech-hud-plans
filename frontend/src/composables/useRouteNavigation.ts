import { onScopeDispose, readonly, ref } from 'vue';
import { useRouter, type RouteLocationRaw } from 'vue-router';

export function useRouteNavigation() {
    const router = useRouter();
    const navigating = ref(false);
    const navigationFailed = ref(false);
    let disposed = false;

    onScopeDispose(() => {
        // Notification actions can still navigate after the page closes.
        disposed = true;
    });

    function clearNavigationFailure(): void {
        if (!disposed) navigationFailed.value = false;
    }

    async function navigate(method: 'push' | 'replace', to: RouteLocationRaw): Promise<void> {
        if (navigating.value) return;
        navigating.value = true;
        let failed = false;
        try {
            failed = Boolean(await router[method](to));
        } catch {
            failed = true;
        } finally {
            if (!disposed) navigationFailed.value = failed;
            navigating.value = false;
        }
    }

    return {
        navigating: readonly(navigating),
        navigationFailed: readonly(navigationFailed),
        clearNavigationFailure,
        push: (to: RouteLocationRaw) => navigate('push', to),
        replace: (to: RouteLocationRaw) => navigate('replace', to),
    };
}
