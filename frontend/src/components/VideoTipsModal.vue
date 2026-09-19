<template>
    <q-dialog v-model="isOpen" :aria-labelledby="titleId">
        <q-card class="video-tips-modal column no-wrap">
            <q-card-section>
                <h2 :id="titleId" class="text-h6 text-weight-bold q-my-none">
                    {{ t('capture.tipsTitle') }}
                </h2>
            </q-card-section>

            <q-card-section class="col scroll q-pt-none">
                <q-list class="q-gutter-y-md">
                    <q-card v-for="tip in tips" :key="tip.icon" flat bordered class="q-py-sm">
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
                                <q-item-label class="text-subtitle1 text-weight-medium">
                                    {{ tip.title }}
                                </q-item-label>
                                <q-item-label caption>{{ tip.meta }}</q-item-label>
                            </q-item-section>
                        </q-item>
                    </q-card>
                </q-list>
            </q-card-section>

            <q-card-actions align="between">
                <q-toggle
                    v-model="localPreferencesStore.hideVideoTips"
                    :label="t('capture.doNotShowTipsAgain')"
                    color="primary"
                />
                <q-btn
                    flat
                    no-caps
                    color="primary"
                    :label="t('common.close')"
                    @click="isOpen = false"
                />
            </q-card-actions>
        </q-card>
    </q-dialog>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue';
import { useI18n } from 'vue-i18n';
import { useLocalPreferencesStore } from 'src/stores/localPreferences';

const isOpen = defineModel<boolean>({ required: true });
const { t } = useI18n();
const titleId = useId();
const localPreferencesStore = useLocalPreferencesStore();

const tips = computed(() => [
    { icon: 'photo_camera', title: t('capture.wideAngleTip'), meta: t('capture.wideAngleHint') },
    { icon: '360', title: t('capture.viewingAnglesTip'), meta: t('capture.viewingAnglesHint') },
    {
        icon: 'directions_walk',
        title: t('capture.walkSlowlyTip'),
        meta: t('capture.walkSlowlyHint'),
    },
    { icon: 'wb_sunny', title: t('capture.wellLitTip'), meta: t('capture.wellLitHint') },
]);
</script>

<style scoped>
.video-tips-modal {
    width: 560px;
    max-width: 100%;
}
</style>
