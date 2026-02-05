<template>
    <q-layout view="lHh Lpr lFf">
        <q-header elevated>
            <q-toolbar>
                <q-btn
                flat
                dense
                round
                icon="menu"
                aria-label="Menu"
                @click="toggleLeftDrawer"
                />
                
                <q-toolbar-title>
                    Quasar App
                </q-toolbar-title>
                
                <div>Quasar v{{ $q.version }}</div>
            </q-toolbar>
        </q-header>
        
        <q-page-container>
            <router-view />
        </q-page-container>

        <q-drawer v-model="leftDrawerOpen" show-if-above side="left" bordered width-hint="450" :width="450">
            <router-view name="drawer" />
        </q-drawer>
    </q-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const leftDrawerOpen = ref(false);

function toggleLeftDrawer () {
    leftDrawerOpen.value = !leftDrawerOpen.value;
}
</script>
