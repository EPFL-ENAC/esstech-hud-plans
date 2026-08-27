<template>
    <q-page class="od-page bg-white text-dark" style="display: flex; flex-direction: column">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                color="primary"
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">My Building - 2D Plan</div>
        </div>

        <div class="od-plan-toolbar">
            <button
                v-for="tool in tools"
                :key="tool.name"
                type="button"
                class="od-tool-btn"
                :class="{ 'is-active': activeTool === tool.name }"
                @click="activeTool = tool.name"
            >
                <q-icon :name="tool.icon" class="od-tool-btn__icon" />
                <span class="od-tool-btn__label">{{ tool.label }}</span>
            </button>
        </div>

        <div class="od-plan-viewer">
            <svg viewBox="0 0 320 320" class="od-2d-plan">
                <g fill="none" stroke="var(--q-primary)" stroke-width="4" stroke-linecap="square">
                    <path
                        d="M40 40 h240 v40 h-80 v40 h-40 v-40 h-120 v120 h120 v-60 h40 v60 h120 v-160 h-80"
                    />
                    <path d="M40 200 h120 v80 h-120 z" />
                    <path d="M200 240 h120 v40 h-120 z" />
                    <path d="M160 80 v40" />
                    <path d="M200 80 v40" />
                    <path d="M80 200 v80" />
                    <path d="M240 240 v40" />
                </g>
            </svg>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const activeTool = ref('measure');
const tools = [
    { name: 'measure', label: 'Measure', icon: 'straighten' },
    { name: 'slice', label: 'Slice', icon: 'content_cut' },
    { name: 'note', label: 'Note', icon: 'notes' },
];
</script>

<style scoped>
.od-2d-plan {
    width: 90%;
    max-width: 360px;
    height: auto;
}
</style>
