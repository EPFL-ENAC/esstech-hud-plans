<template>
    <q-layout view="lHh LpR lFf">
        <q-page-container>
            <q-page class="row items-center justify-center">
                <div class="column items-center q-gutter-y-md">
                    <h1 class="text-h4 q-ma-none">Points of Home</h1>
                    <q-btn label="Sign in" color="primary" size="lg" @click="signIn" />
                </div>
            </q-page>
        </q-page-container>
    </q-layout>
</template>

<script setup lang="ts">
import { buildKeycloakLoginUrl } from 'src/lib/auth';

function signIn() {
    window.location.href = buildKeycloakLoginUrl();
}
</script>
