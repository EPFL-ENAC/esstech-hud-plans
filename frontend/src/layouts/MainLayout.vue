<template>
    <q-layout view="hhh Lpr lFf">
        <q-page-container>
            <router-view />
        </q-page-container>

        <q-footer bordered class="od-bottom-tabs">
            <q-tabs no-caps indicator-color="transparent" active-color="primary" align="justify">
                <q-route-tab to="/home" icon="home" label="Home" />
                <q-route-tab to="/capture" icon="photo_camera" label="Capture" />
                <q-route-tab to="/library" icon="list" label="Library" />
                <q-route-tab to="/more" icon="more_horiz" label="More" />
            </q-tabs>
        </q-footer>

        <q-drawer v-model="drawerOpen" side="left" bordered width-hint="450" :width="450">
            <router-view name="drawer" />
        </q-drawer>
    </q-layout>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();

const drawerOpen = computed(() => route.path.startsWith('/splat'));
</script>
