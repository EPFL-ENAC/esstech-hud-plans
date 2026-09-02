<template>
    <q-page
        class="bg-white text-dark q-px-md"
        style="padding-top: 64px; display: flex; flex-direction: column"
    >
        <page-header title="My Building - 2D Plan" />

        <div
            class="row justify-center q-gutter-x-xl q-py-sm q-mb-md"
            style="border-bottom: 1px solid #e5e5ea"
        >
            <q-btn
                v-for="tool in tools"
                :key="tool.name"
                stack
                flat
                no-caps
                :color="activeTool === tool.name ? 'primary' : 'grey-7'"
                @click="activeTool = tool.name"
            >
                <q-icon :name="tool.icon" size="22px" />
                <span class="text-caption text-weight-medium">{{ tool.label }}</span>
            </q-btn>
        </div>

        <q-card
            flat
            bordered
            square
            class="bg-grey-3 flex flex-center"
            style="flex: 1; min-height: 320px; overflow: hidden"
        >
            <svg viewBox="0 0 320 320" style="width: 90%; max-width: 360px; height: auto">
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
        </q-card>
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import PageHeader from 'src/components/PageHeader.vue';

const activeTool = ref('measure');
const tools = [
    { name: 'measure', label: 'Measure', icon: 'straighten' },
    { name: 'slice', label: 'Slice', icon: 'content_cut' },
    { name: 'note', label: 'Note', icon: 'notes' },
];
</script>
