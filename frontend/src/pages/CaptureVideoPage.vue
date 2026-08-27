<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
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
            <div class="od-topbar__title">Capture video</div>
        </div>

        <div class="od-placeholder">View of Camera</div>

        <section class="q-mb-lg">
            <h2 class="od-h-section q-mb-lg">Tips for best results</h2>
            <q-list class="q-gutter-y-md">
                <q-item v-for="tip in tips" :key="tip.icon" class="od-card-row">
                    <q-item-section avatar>
                        <div class="od-icon-box">
                            <q-icon :name="tip.icon" />
                        </div>
                    </q-item-section>
                    <q-item-section class="q-gutter-y-xs">
                        <div class="od-title">{{ tip.title }}</div>
                        <div class="od-subtitle">{{ tip.meta }}</div>
                    </q-item-section>
                </q-item>
            </q-list>
        </section>

        <q-btn
            label="Start Recording"
            color="primary"
            class="od-btn full-width"
            unelevated
            no-caps
        />
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const tips = ref([
    { icon: 'photo_camera', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'timer', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'swap_vert', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'fullscreen', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
]);
</script>
