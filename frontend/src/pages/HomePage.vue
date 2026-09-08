<template>
    <q-page class="bg-white text-dark q-pb-xl">
        <section class="q-px-md q-pt-md q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-md">{{ t('home.quickActions') }}</h2>
            <div class="row q-col-gutter-md">
                <div class="col-6">
                    <q-card
                        flat
                        bordered
                        clickable
                        class="link-card"
                        @click="$router.push('/capture')"
                    >
                        <q-card-section class="column">
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon name="photo_camera" />
                            </q-avatar>
                            <div class="text-subtitle1 text-weight-medium q-mt-sm">
                                {{ t('capture.newCapture') }}
                            </div>
                        </q-card-section>
                    </q-card>
                </div>
                <div class="col-6">
                    <q-card
                        flat
                        bordered
                        clickable
                        class="link-card"
                        @click="$router.push('/library')"
                    >
                        <q-card-section class="column">
                            <q-avatar
                                square
                                size="48px"
                                font-size="24px"
                                color="white"
                                text-color="primary"
                                class="avatar-icon"
                            >
                                <q-icon name="list" />
                            </q-avatar>
                            <div class="text-subtitle1 text-weight-medium q-mt-sm">
                                {{ t('navigation.library') }}
                            </div>
                        </q-card-section>
                    </q-card>
                </div>
            </div>
        </section>

        <section class="q-px-md q-pt-md q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-md q-px-md">{{ t('home.inProgress') }}</h2>

            <my-buildings-list :reconstruction-status="'processing'" />
        </section>

        <section class="q-px-md q-pt-md q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-md q-px-md">{{ t('home.recent') }}</h2>

            <my-buildings-list :reconstruction-status="'idle'" />
        </section>
    </q-page>
</template>

<script setup lang="ts">
import MyBuildingsList from 'src/components/MyBuildingsList.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
</script>
