<template>
    <q-page class="od-page" style="display: flex; flex-direction: column">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">My Building - 3D Plan</div>
        </div>

        <div class="od-plan-viewer">
            <svg class="od-axis" viewBox="0 0 40 40">
                <line x1="20" y1="20" x2="36" y2="8" stroke="#ff3b30" stroke-width="2" />
                <line x1="20" y1="20" x2="8" y2="36" stroke="#34c759" stroke-width="2" />
                <line x1="20" y1="20" x2="10" y2="10" stroke="#5ac8fa" stroke-width="2" />
                <circle cx="20" cy="20" r="3" fill="#1c1c1e" />
            </svg>

            <div class="od-viewer-controls">
                <button type="button" class="od-btn od-btn--icon od-btn--outline">
                    <q-icon name="square" />
                </button>
                <button type="button" class="od-btn od-btn--icon od-btn--outline">
                    <q-icon name="view_in_ar" />
                </button>
            </div>

            <svg viewBox="0 0 200 200" class="od-3d-model">
                <polygon points="100,20 180,70 180,150 100,200 20,150 20,70" />
                <polygon points="100,20 180,70 100,110 20,70" fill="rgba(0,169,165,0.25)" />
                <polygon points="100,110 180,70 180,150 100,200" fill="rgba(0,169,165,0.35)" />
            </svg>
        </div>

        <q-btn
            label="Export to interactive 2D plan view"
            color="primary"
            class="od-btn od-btn--primary full-width q-mt-md"
            unelevated
            no-caps
        />
    </q-page>
</template>

<script setup lang="ts">
//
</script>
