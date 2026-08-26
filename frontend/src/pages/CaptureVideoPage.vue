<template>
    <q-page class="od-page od-page--scroll">
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
            <div class="od-topbar__title">Capture video</div>
        </div>

        <div class="od-placeholder od-placeholder--camera">View of Camera</div>

        <section class="od-section">
            <h2 class="od-section-title">Tips for best results</h2>
            <div class="od-list">
                <div class="od-list-row">
                    <div class="od-plan-card__icon">
                        <q-icon name="photo_camera" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-list-row__title">Use wide-angle lens</div>
                        <div class="od-list-row__meta">Set to 0.5x or widest available</div>
                    </div>
                </div>

                <div class="od-list-row">
                    <div class="od-plan-card__icon">
                        <q-icon name="timer" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-list-row__title">Use wide-angle lens</div>
                        <div class="od-list-row__meta">Set to 0.5x or widest available</div>
                    </div>
                </div>

                <div class="od-list-row">
                    <div class="od-plan-card__icon">
                        <q-icon name="swap_vert" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-list-row__title">Use wide-angle lens</div>
                        <div class="od-list-row__meta">Set to 0.5x or widest available</div>
                    </div>
                </div>

                <div class="od-list-row">
                    <div class="od-plan-card__icon">
                        <q-icon name="fullscreen" />
                    </div>
                    <div class="od-list-row__content">
                        <div class="od-list-row__title">Use wide-angle lens</div>
                        <div class="od-list-row__meta">Set to 0.5x or widest available</div>
                    </div>
                </div>
            </div>
        </section>

        <q-btn
            label="Start Recording"
            color="primary"
            class="od-btn od-btn--primary full-width"
            unelevated
            no-caps
        />
    </q-page>
</template>

<script setup lang="ts">
//
</script>
