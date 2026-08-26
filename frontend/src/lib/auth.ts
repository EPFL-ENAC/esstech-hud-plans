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
    return !!getAccessToken();
}

/** Clear the stored token. The caller is responsible for navigation. */
export function logout(): void {
    clearAccessToken();
}

/** Build the Keycloak authorization URL for the login redirect. */
export function buildKeycloakLoginUrl(): string {
    const url = new URL(`${keycloakEndpoint}/realms/${keycloakRealm}/protocol/openid-connect/auth`);
    url.search = new URLSearchParams({
        client_id: keycloakClientId,
        redirect_uri: keycloakRedirectUri,
        response_type: 'code',
        scope: 'openid profile email',
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
