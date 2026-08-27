<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <h1 class="od-h-page q-mb-lg">How would you like to capture?</h1>

        <q-list class="q-gutter-y-md">
            <q-item
                class="od-card-row"
                clickable
                tabindex="0"
                @click="$router.push('/capture/video')"
            >
                <q-item-section avatar>
                    <div class="od-icon-box">
                        <q-icon name="videocam" />
                    </div>
                </q-item-section>
                <q-item-section class="q-gutter-y-xs">
                    <div class="od-title">Capture video</div>
                    <div class="od-subtitle">Use your camera</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="chevron_right" size="20px" color="dark" />
                </q-item-section>
            </q-item>

            <q-item
                class="od-card-row"
                clickable
                tabindex="0"
                @click="$router.push('/capture/new')"
            >
                <q-item-section avatar>
                    <div class="od-icon-box">
                        <q-icon name="download" />
                    </div>
                </q-item-section>
                <q-item-section class="q-gutter-y-xs">
                    <div class="od-title">Upload from device</div>
                    <div class="od-subtitle">Choose an existing video file</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="chevron_right" size="20px" color="dark" />
                </q-item-section>
            </q-item>
        </q-list>
    </q-page>
</template>

<script setup lang="ts">
//
</script>
