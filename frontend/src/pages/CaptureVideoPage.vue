<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header :title="t('capture.captureVideo')" />

        <camera-viewfinder class="q-mb-md" />

        <section class="q-mb-lg">
            <h2 class="text-h6 text-weight-bold q-mb-lg">{{ t('capture.tipsTitle') }}</h2>
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

        <q-banner v-if="handoffError" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ handoffError }}
        </q-banner>

        <!-- Recording starts on the dedicated full-screen capture page. -->
        <q-btn
            :label="t('capture.startRecording')"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            @click="openCapture"
        />
    </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import PageHeader from 'src/components/PageHeader.vue';
import CameraViewfinder from 'src/components/CameraViewfinder.vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const router = useRouter();
const handoffError = ref('');

async function openCapture(): Promise<void> {
    const failure = await router.push('/capture/record');
    if (failure) {
        handoffError.value = t('capture.record.openFailed');
    }
}

const tips = computed(() => [
    { icon: 'photo_camera', title: t('capture.wideAngleTip'), meta: t('capture.wideAngleHint') },
    { icon: 'timer', title: t('capture.wideAngleTip'), meta: t('capture.wideAngleHint') },
    { icon: 'swap_vert', title: t('capture.wideAngleTip'), meta: t('capture.wideAngleHint') },
    { icon: 'fullscreen', title: t('capture.wideAngleTip'), meta: t('capture.wideAngleHint') },
]);
</script>
