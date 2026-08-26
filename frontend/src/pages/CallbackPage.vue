<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="row items-center justify-center">
                <div v-if="status === 'exchanging'" class="column items-center q-gutter-y-md">
                    <q-spinner size="lg" color="primary" />
                    <div>Signing you in...</div>
                </div>
                <div v-else class="text-negative">{{ status }}</div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { baseUrl, keycloakRedirectUri } from 'boot/api';
import { setAccessToken } from 'src/lib/auth';

const route = useRoute();
const router = useRouter();
const status = ref('exchanging');

onMounted(async () => {
    // The auth response parameters arrive either in the fragment the router
    // exposes as query (route.query) or in window.location.search when Keycloak
    // puts them before the hash. Read both so the exchange works either way.
    const read = (name: string) =>
        (route.query[name] as string | undefined) ??
        new URLSearchParams(window.location.search).get(name) ??
        undefined;

    const code = read('code');
    if (!code) {
        status.value = 'Missing authorization code';
        return;
    }

    // Login CSRF protection: the state returned by Keycloak must match the one
    // we generated when starting the login (stored in sessionStorage).
    const expectedState = sessionStorage.getItem('oauth_state');
    sessionStorage.removeItem('oauth_state');
    const returnedState = read('state');
    if (!returnedState || !expectedState || returnedState !== expectedState) {
        status.value = 'Invalid OAuth state. Please try signing in again.';
        return;
    }

    // Reuse the exact redirect URI used in the login request so the token
    // exchange matches what Keycloak registered for this authorization code.
    const redirectUri = keycloakRedirectUri;
    try {
        const response = await fetch(`${baseUrl}/auth/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, redirect_uri: redirectUri }),
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Sign in failed');
        }
        const data = await response.json();
        setAccessToken(data.access_token);
        // Drop the authorization code from the address bar, then go home.
        window.history.replaceState(null, '', window.location.pathname);
        await router.replace('/');
    } catch (error) {
        // Show the error on the page (instead of silently returning to /login)
        // so an exchange failure is visible and diagnosable.
        status.value = 'Error: ' + (error as Error).message;
    }
});
</script>
