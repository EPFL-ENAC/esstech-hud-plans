import {
    baseUrl,
    keycloakClientId,
    keycloakEndpoint,
    keycloakRealm,
    keycloakRedirectUri,
} from 'boot/api';

const TOKEN_KEY = 'access_token';

export function getAccessToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
    localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
    const token = getAccessToken();
    if (!token) {
        return false;
    }
    const payload = decodeJwtPayload();
    // Treat missing/parsing-failure as unauthenticated rather than trusting a
    // token we cannot inspect; expiry is read from the "exp" claim.
    if (!payload) {
        return false;
    }
    const exp = payload.exp as number | undefined;
    if (typeof exp === 'number' && exp * 1000 <= Date.now()) {
        return false;
    }
    return true;
}

/**
 * Decode (without verifying) the JWT payload of the stored access token.
 * Returns null when the token is missing or malformed.
 */
function decodeJwtPayload(): Record<string, unknown> | null {
    const token = getAccessToken();
    if (!token) {
        return null;
    }
    const part = token.split('.')[1];
    if (!part) {
        return null;
    }
    try {
        // Base64url -> standard base64 -> UTF-8 JSON.
        const base64 = part.replace(/-/g, '+').replace(/_/g, '/');
        const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
        const json = decodeURIComponent(
            Array.from(
                atob(padded),
                (c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'),
            ).join(''),
        );
        return JSON.parse(json) as Record<string, unknown>;
    } catch {
        return null;
    }
}

/** Current account identity for user-scoped query caches. */
export function getAuthSubject(): string | null {
    const subject = decodeJwtPayload()?.sub;
    return typeof subject === 'string' && subject.length > 0 ? subject : null;
}

/** Roles granted to this client for the app's Keycloak client. */
export function getClientRoles(): string[] {
    const payload = decodeJwtPayload();
    if (!payload) {
        return [];
    }
    const resourceAccess = payload.resource_access as
        | Record<string, { roles?: string[] }>
        | undefined;
    return resourceAccess?.[keycloakClientId]?.roles ?? [];
}

/** Realm (global) roles granted to the user. */
export function getRealmRoles(): string[] {
    const payload = decodeJwtPayload();
    if (!payload) {
        return [];
    }
    const realmAccess = payload.realm_access as { roles?: string[] } | undefined;
    return realmAccess?.roles ?? [];
}

/** True when the user holds the client role "admin" for this app. */
export function isAdmin(): boolean {
    return getClientRoles().includes('admin');
}

/** Clear the stored token. The caller is responsible for navigation. */
export function logout(): void {
    clearAccessToken();
}

/** Remove every trace of the app on this device: storage, caches, databases. */
export async function clearLocalData(): Promise<void> {
    localStorage.clear();
    sessionStorage.clear();
    if (typeof caches !== 'undefined') {
        const names = await caches.keys();
        await Promise.all(names.map((name) => caches.delete(name)));
    }
    if (typeof indexedDB.databases === 'function') {
        const names = (await indexedDB.databases())
            .map(({ name }) => name)
            .filter((name): name is string => !!name);
        await Promise.all(names.map(deleteIndexedDatabase));
    }
}

/** deleteDatabase returns an IDBRequest, so wrap it; best-effort, never rejects. */
function deleteIndexedDatabase(name: string): Promise<void> {
    return new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(name);
        request.onsuccess = request.onerror = request.onblocked = () => resolve();
    });
}

/** Build the Keycloak authorization URL for the login redirect. */
export function buildKeycloakLoginUrl(): string {
    // Random state for login CSRF protection: we verify it on the callback so
    // a forged/attacker-initiated login cannot complete against our session.
    const state = window.crypto.randomUUID();
    sessionStorage.setItem('oauth_state', state);

    const url = new URL(`${keycloakEndpoint}/realms/${keycloakRealm}/protocol/openid-connect/auth`);
    url.search = new URLSearchParams({
        client_id: keycloakClientId,
        redirect_uri: keycloakRedirectUri,
        response_type: 'code',
        scope: 'openid profile email',
        state,
    }).toString();
    return url.toString();
}

/**
 * Wrapper around fetch that automatically attaches the stored bearer token
 * to every request. A 403 with detail "terms_not_accepted" from a gated
 * endpoint sends the user to the terms screen.
 */
export async function authFetch(
    input: RequestInfo | URL,
    init: RequestInit = {},
): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = getAccessToken();
    if (token) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    const response = await fetch(input, { ...init, headers });
    if (response.status === 403) {
        // Clone before reading so the caller can still consume the body. The
        // hash navigation avoids a circular import with the router.
        const body = (await response
            .clone()
            .json()
            .catch(() => null)) as { detail?: string } | null;
        if (body?.detail === 'terms_not_accepted') {
            window.location.hash = '#/terms';
        }
    }
    return response;
}

/** Cache (per page load) of whether the current user accepted the terms. */
let termsAcceptedPromise: Promise<boolean> | null = null;

/**
 * Fetch GET /user/me and report whether terms are accepted. Cached in a
 * module-level promise so the router guard runs at most one fetch per page
 * load; pass refresh to reset the cache after accepting.
 */
export function getTermsAccepted(refresh = false): Promise<boolean> {
    if (refresh || termsAcceptedPromise === null) {
        termsAcceptedPromise = (async () => {
            try {
                const response = await authFetch(`${baseUrl}/user/me`);
                if (!response.ok) {
                    return false;
                }
                const user = (await response.json()) as { terms_accepted?: boolean };
                return user.terms_accepted === true;
            } catch {
                return false;
            }
        })();
    }
    return termsAcceptedPromise;
}
