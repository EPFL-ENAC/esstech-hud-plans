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
    // With hash-based routing, Keycloak appends the auth parameters to the URL
    // query string (window.location.search) rather than to the hash the router
    // reads. Read the code from both places so the exchange works either way.
    const code =
        (route.query.code as string | undefined) ??
        new URLSearchParams(window.location.search).get('code') ??
        undefined;
    if (!code) {
        status.value = 'Missing authorization code';
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
        status.value = 'Error: ' + (error as Error).message;
        await router.replace('/login');
    }
});
</script>
