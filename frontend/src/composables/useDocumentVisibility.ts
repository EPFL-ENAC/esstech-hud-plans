import { onScopeDispose, readonly, ref, type Ref } from 'vue';

export function useDocumentVisibility(): Readonly<Ref<boolean>> {
    const visible = ref(document.visibilityState === 'visible');

    function updateVisibility(): void {
        visible.value = document.visibilityState === 'visible';
    }

    document.addEventListener('visibilitychange', updateVisibility);

    onScopeDispose(() => {
        document.removeEventListener('visibilitychange', updateVisibility);
    });

    return readonly(visible);
}
