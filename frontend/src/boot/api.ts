interface CustomWindow extends Window {
    env: {
        API_URL: string;
        API_PATH: string;
        KEYCLOAK_ENDPOINT: string;
        KEYCLOAK_REALM: string;
        KEYCLOAK_CLIENT_ID: string;
        SENTRY_ENVIRONMENT?: string;
        SENTRY_RATE?: string;
    };
}

const appEnv = (window as unknown as CustomWindow).env;
export const baseUrl = `${appEnv.API_URL}${appEnv.API_PATH}`;
export const keycloakEndpoint = appEnv.KEYCLOAK_ENDPOINT;
export const keycloakRealm = appEnv.KEYCLOAK_REALM;
export const keycloakClientId = appEnv.KEYCLOAK_CLIENT_ID;

export const keycloakRedirectUri = `${window.location.origin}${window.location.pathname}#/callback`;
