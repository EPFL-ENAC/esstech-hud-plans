import { keycloakClientId, keycloakEndpoint, keycloakRealm, keycloakRedirectUri } from 'boot/api';

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
 * to every request.
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
    return fetch(input, { ...init, headers });
}
