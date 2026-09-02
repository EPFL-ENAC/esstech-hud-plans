<template>
    <q-page
        class="bg-white text-dark q-px-md"
        style="padding-top: 64px; display: flex; flex-direction: column"
    >
        <page-header title="My Building - 3D Plan" />

        <q-card
            flat
            bordered
            square
            class="bg-grey-3 relative-position flex flex-center"
            style="flex: 1; min-height: 400px; overflow: hidden"
        >
            <svg
                class="absolute"
                viewBox="0 0 40 40"
                style="top: 16px; left: 16px; width: 40px; height: 40px"
            >
                <line x1="20" y1="20" x2="36" y2="8" stroke="#ff3b30" stroke-width="2" />
                <line x1="20" y1="20" x2="8" y2="36" stroke="#34c759" stroke-width="2" />
                <line x1="20" y1="20" x2="10" y2="10" stroke="#5ac8fa" stroke-width="2" />
                <circle cx="20" cy="20" r="3" fill="#1c1c1e" />
            </svg>

            <div class="absolute column q-gutter-sm" style="top: 16px; right: 16px">
                <q-btn round flat dense icon="square" />
                <q-btn round flat dense icon="view_in_ar" />
            </div>

            <svg viewBox="0 0 200 200" style="width: 60%; max-width: 280px">
                <polygon points="100,20 180,70 180,150 100,200 20,150 20,70" />
                <polygon points="100,20 180,70 100,110 20,70" fill="rgba(0,169,165,0.25)" />
                <polygon points="100,110 180,70 180,150 100,200" fill="rgba(0,169,165,0.35)" />
            </svg>
        </q-card>

        <q-btn
            label="Export to interactive 2D plan view"
            color="primary"
            class="full-width q-mt-md"
            unelevated
            no-caps
        />
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
//
</script>
