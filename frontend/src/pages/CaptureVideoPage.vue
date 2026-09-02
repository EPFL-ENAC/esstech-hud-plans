<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header title="Capture video" />

        <q-card flat bordered square class="bg-grey-3 flex flex-center text-grey-7 q-mb-md">
            <div class="column items-center q-py-xl q-gutter-sm">
                <q-icon name="videocam" size="48px" />
                <span>View of Camera</span>
            </div>
        </q-card>

        <section class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-lg">Tips for best results</h2>
            <q-list class="q-gutter-y-md">
                <q-card
                    v-for="tip in tips"
                    :key="tip.icon"
                    flat
                    bordered
                    class="q-py-sm items-center"
                >
                    <q-item>
                        <q-item-section avatar>
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon :name="tip.icon" />
                            </q-avatar>
                        </q-item-section>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium">{{
                                tip.title
                            }}</q-item-label>
                            <q-item-label caption>{{ tip.meta }}</q-item-label>
                        </q-item-section>
                    </q-item>
                </q-card>
            </q-list>
        </section>

        <q-btn label="Start Recording" color="primary" class="full-width" unelevated no-caps />
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import PageHeader from 'src/components/PageHeader.vue';

const tips = ref([
    { icon: 'photo_camera', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'timer', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'swap_vert', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
    { icon: 'fullscreen', title: 'Use wide-angle lens', meta: 'Set to 0.5x or widest available' },
]);
</script>
