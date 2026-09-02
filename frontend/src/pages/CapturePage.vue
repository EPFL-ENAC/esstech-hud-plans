<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl">
        <h1 class="text-h5 text-weight-bold q-mb-lg">How would you like to capture?</h1>

        <q-list class="q-gutter-y-md">
            <q-card flat bordered clickable class="q-py-sm" @click="$router.push('/capture/video')">
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
                            <q-icon name="videocam" />
                        </q-avatar>
                    </q-item-section>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium"
                            >Capture video</q-item-label
                        >
                        <q-item-label caption>Use your camera</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered clickable class="q-py-sm" @click="$router.push('/capture/new')">
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
                            <q-icon name="download" />
                        </q-avatar>
                    </q-item-section>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium"
                            >Upload from device</q-item-label
                        >
                        <q-item-label caption>Choose an existing video file</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>
        </q-list>
    </q-page>
</template>

<script setup lang="ts">
//
</script>
