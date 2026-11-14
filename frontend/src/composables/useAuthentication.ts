import { computed, onScopeDispose, shallowRef } from 'vue';
import {
    getAuthSubject,
    isAuthenticated as readIsAuthenticated,
    subscribeAuthChanges,
} from 'src/lib/auth';

export interface AuthenticationState {
    readonly ownerId: string | null;
    readonly isAuthenticated: boolean;
}

interface AuthenticationOptions {
    onChange?: (current: AuthenticationState, previous: AuthenticationState) => void;
}

function readAuthentication(): AuthenticationState {
    return {
        ownerId: getAuthSubject(),
        isAuthenticated: readIsAuthenticated(),
    };
}

export function useAuthentication({ onChange }: AuthenticationOptions = {}) {
    const state = shallowRef(readAuthentication());
    const ownerId = computed(() => state.value.ownerId);
    const isAuthenticated = computed(() => state.value.isAuthenticated);

    /** Synchronously reread the locally stored session. */
    function refreshAuthentication(): boolean {
        const previous = state.value;
        const current = readAuthentication();

        if (
            current.ownerId !== previous.ownerId ||
            current.isAuthenticated !== previous.isAuthenticated
        ) {
            // Publish both fields together before notifying consumers.
            state.value = current;
            onChange?.(current, previous);
        }

        return state.value.isAuthenticated;
    }

    const unsubscribe = subscribeAuthChanges(refreshAuthentication);
    window.addEventListener('focus', refreshAuthentication);
    onScopeDispose(() => {
        unsubscribe();
        window.removeEventListener('focus', refreshAuthentication);
    });

    return { ownerId, isAuthenticated, refreshAuthentication };
}
