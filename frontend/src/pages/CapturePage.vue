<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl">
        <h1 class="text-h5 text-weight-bold q-mb-lg">{{ t('capture.chooseMethod') }}</h1>

        <q-list class="q-gutter-y-md">
            <q-card
                flat
                bordered
                clickable
                class="link-card q-py-sm"
                @click="$router.push('/capture/video')"
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
                            <q-icon name="videocam" />
                        </q-avatar>
                    </q-item-section>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">{{
                            t('capture.captureVideo')
                        }}</q-item-label>
                        <q-item-label caption>{{ t('capture.useCamera') }}</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card
                flat
                bordered
                clickable
                class="link-card q-py-sm"
                @click="$router.push('/capture/new')"
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
                            <q-icon name="download" />
                        </q-avatar>
                    </q-item-section>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">{{
                            t('capture.upload')
                        }}</q-item-label>
                        <q-item-label caption>{{ t('capture.chooseExistingVideo') }}</q-item-label>
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
import { useI18n } from 'vue-i18n';

const { t } = useI18n();
</script>
