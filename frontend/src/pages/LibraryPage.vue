<template>
    <q-page class="bg-white text-dark q-pb-xl" style="padding-top: 64px">
        <page-header :back="false" title="Library">
            <q-btn
                flat
                no-caps
                color="primary"
                label="New Capture"
                @click="$router.push('/capture')"
            />
        </page-header>

        <q-tabs
            v-model="tab"
            no-caps
            indicator-color="primary"
            align="left"
            bordered
            class="q-px-md q-mb-md"
        >
            <q-tab name="list" label="List" />
            <q-tab name="map" label="Map" />
        </q-tabs>

        <q-input
            v-show="tab === 'list'"
            v-model="search"
            :debounce="300"
            clearable
            outlined
            rounded
            placeholder="Search buildings"
            aria-label="Search buildings"
            class="q-mx-md q-mb-md"
        >
            <template #prepend>
                <q-icon name="search" />
            </template>
        </q-input>

        <keep-alive>
            <my-buildings-list v-if="tab === 'list'" :search="search" />
            <my-buildings-map v-else />
        </keep-alive>
    </q-page>
</template>

<script setup lang="ts">
import { defineAsyncComponent } from 'vue';
import { storeToRefs } from 'pinia';
import MyBuildingsList from 'src/components/MyBuildingsList.vue';
import PageHeader from 'src/components/PageHeader.vue';
import { useUiStore } from 'src/stores/ui';

const MyBuildingsMap = defineAsyncComponent(() => import('src/components/MyBuildingsMap.vue'));
const { libraryTab: tab, librarySearch: search } = storeToRefs(useUiStore());
</script>
