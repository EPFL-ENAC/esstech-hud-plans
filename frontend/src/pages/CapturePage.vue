<template>
    <q-page class="od-page od-page--scroll">
        <h1 class="od-page-title">How would you like to capture?</h1>

        <div class="od-list">
            <div class="od-list-row" tabindex="0" @click="$router.push('/capture/video')">
                <div class="od-plan-card__icon">
                    <q-icon name="videocam" />
                </div>
                <div class="od-list-row__content">
                    <div class="od-list-row__title">Capture video</div>
                    <div class="od-list-row__meta">Use your camera</div>
                </div>
                <q-icon name="chevron_right" class="od-list-row__chevron" />
            </div>

            <div class="od-list-row" tabindex="0" @click="$router.push('/capture/new')">
                <div class="od-plan-card__icon">
                    <q-icon name="download" />
                </div>
                <div class="od-list-row__content">
                    <div class="od-list-row__title">Upload from device</div>
                    <div class="od-list-row__meta">Choose an existing video file</div>
                </div>
                <q-icon name="chevron_right" class="od-list-row__chevron" />
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
//
</script>
