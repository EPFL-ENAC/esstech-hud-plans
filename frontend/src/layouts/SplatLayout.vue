<template>
    <q-layout view="hhh Lpr lFf" class="app-layout">
        <q-page-container>
            <router-view v-slot="{ Component, route }">
                <component :is="Component" :key="route.path" />
            </router-view>
        </q-page-container>

        <!-- Left drawer hosts the splat pipeline (full-screen splat page).
             This layout is used only by the splat route, so the drawer is
             always shown. The main navigation layout is unaffected. -->
        <q-drawer :model-value="pipelineOpen" side="left" bordered width-hint="450" :width="450">
            <router-view name="drawer" />
        </q-drawer>
    </q-layout>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();

// The splat pipeline drawer is visible whenever the active route is a splat
// route. Kept as a computed so the drawer stays in sync with the route.
const pipelineOpen = computed(() => route.path.startsWith('/splat'));
</script>
