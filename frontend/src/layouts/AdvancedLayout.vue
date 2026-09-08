<template>
    <q-layout view="lHh Lpr lFf">
        <q-header elevated>
            <q-toolbar>
                <q-btn flat dense round icon="menu" aria-label="Menu" @click="toggleLeftDrawer" />

                <q-toolbar-title> Quasar App </q-toolbar-title>

                <q-btn
                    flat
                    dense
                    icon="logout"
                    label="Logout"
                    aria-label="Log out"
                    @click="handleLogout"
                />
            </q-toolbar>
        </q-header>

        <q-page-container>
            <router-view />
        </q-page-container>

        <q-drawer
            v-model="leftDrawerOpen"
            show-if-above
            side="left"
            bordered
            width-hint="450"
            :width="450"
        >
            <router-view name="drawer" />
        </q-drawer>
    </q-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { logout } from 'src/lib/auth';

const leftDrawerOpen = ref(false);
const router = useRouter();

function toggleLeftDrawer() {
    leftDrawerOpen.value = !leftDrawerOpen.value;
}

function handleLogout() {
    logout();
    // Navigate via the router so the hash-mode URL stays clean (#/login)
    // instead of appending a real /login path segment.
    void router.push('/login');
}
</script>
