<template>
    <q-page class="capture-draft-page">
        <page-header :title="t('reconstructions.new')">
            <q-btn
                v-if="draftSource?.hasUpload"
                flat
                no-caps
                color="primary"
                icon="refresh"
                :label="t('uploads.refresh')"
                :disable="draftSource?.isLoading"
                @click="draftSource?.refetch()"
            />
        </page-header>

        <p v-if="loadStatus === 'loading'" role="status">{{ t('capture.draft.loading') }}</p>
        <q-banner v-else-if="loadStatus === 'error'" class="bg-red-1 text-negative" role="alert">
            {{ t('capture.draft.loadFailed') }}
            <template #action>
                <q-btn flat no-caps :label="t('common.retry')" @click="retryLoad" />
            </template>
        </q-banner>
        <div v-else-if="loadStatus === 'missing'">
            <p role="status">{{ t('capture.draft.unavailable') }}</p>
            <q-btn
                outline
                no-caps
                color="primary"
                :label="t('capture.newCapture')"
                :to="{ name: 'capture-new', query: { buildingId: route.query.buildingId } }"
            />
        </div>

        <template v-if="draft">
            <capture-draft-source-panel
                ref="draftSource"
                :draft="draft"
                :upload-state="uploadState"
            />

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.destinationBuilding') }}</h2>
                <building-picker v-model="draft.form.buildingSelection" class="q-mb-md" />
            </section>

            <section class="q-mb-xl">
                <h2 class="text-h6 text-weight-bold">{{ t('capture.reconstructionSettings') }}</h2>
                <q-select
                    v-model="draft.form.preset"
                    outlined
                    :options="presetOptions"
                    emit-value
                    map-options
                    :label="t('capture.preset')"
                    class="q-mb-xl"
                />
                <section
                    v-if="draft.form.preset === 'advanced'"
                    class="q-mb-xl"
                    :aria-label="t('capture.advancedSettings')"
                >
                    <reconstruction-settings v-model="draft.form.advancedSettings" />
                    <p v-if="!hasValidSettings" class="text-negative q-mt-md" role="alert">
                        {{ t('capture.invalidSettings') }}
                    </p>
                </section>
            </section>

            <q-banner
                v-if="saveStatus === 'error'"
                class="bg-red-1 text-negative q-mb-md"
                role="alert"
            >
                {{ t('capture.draft.saveFailed') }}
                <template #action>
                    <q-btn flat no-caps :label="t('common.retry')" @click="retrySave" />
                </template>
            </q-banner>
            <p v-else class="text-caption text-grey-7" role="status">
                {{ t(saveStatus === 'saving' ? 'capture.draft.saving' : 'capture.draft.saved') }}
            </p>

            <q-btn
                :label="t('capture.startProcessing')"
                color="primary"
                class="full-width"
                unelevated
                no-caps
                disable
            />
        </template>
    </q-page>
</template>

<script setup lang="ts">
import { computed, useTemplateRef } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import BuildingPicker from 'src/components/BuildingPicker.vue';
import CaptureDraftSourcePanel from 'src/components/CaptureDraftSourcePanel.vue';
import PageHeader from 'src/components/PageHeader.vue';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import { useCaptureDraft } from 'src/composables/useCaptureDraft';
import { isValidReconstructionSettings } from 'src/lib/reconstruction-settings';

const props = defineProps<{ draftId: string }>();
const { t } = useI18n();
const route = useRoute();
const draftSource = useTemplateRef<InstanceType<typeof CaptureDraftSourcePanel>>('draftSource');
const { draft, loadStatus, uploadState, saveStatus, retryLoad, retrySave } = useCaptureDraft(
    props.draftId,
);
const presetOptions = computed(() => [
    { value: 'indoors', label: t('capture.presets.indoors') },
    { value: 'outdoors', label: t('capture.presets.outdoors') },
    { value: 'advanced', label: t('capture.presets.advanced') },
]);
const hasValidSettings = computed(
    () => draft.value && isValidReconstructionSettings(draft.value.form.advancedSettings),
);
</script>

<style scoped>
.capture-draft-page {
    padding: 64px 16px 48px;
    background: #fff;
    color: var(--q-dark);
}
</style>
