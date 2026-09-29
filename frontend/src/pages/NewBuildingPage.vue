<template>
    <q-page class="q-pa-md" style="padding-top: 64px">
        <page-header :title="t('buildings.newReconstruction')" />
        <div class="page-content q-gutter-y-md">
            <div class="text-caption text-grey-7">
                {{ t('buildings.newReconstructionDescription') }}
            </div>

            <q-banner v-if="errorMessage" rounded class="bg-red-1 text-negative">
                {{ errorMessage }}
            </q-banner>

            <video-upload-progress v-if="submitting" class="q-mb-md" />

            <q-card flat bordered>
                <q-card-section>
                    <reconstruction-submission-form
                        :loading="submitting"
                        submit-label="Create and submit"
                        @submit="submit"
                    >
                        <template #before>
                            <div class="text-h6">Building</div>
                            <q-input v-model="name" outlined label="Name (optional)" />
                            <div class="row q-col-gutter-md">
                                <q-input
                                    v-model.number="latitude"
                                    class="col-12 col-sm-6"
                                    outlined
                                    clearable
                                    type="number"
                                    min="-90"
                                    max="90"
                                    step="any"
                                    label="Latitude (optional)"
                                />
                                <q-input
                                    v-model.number="longitude"
                                    class="col-12 col-sm-6"
                                    outlined
                                    clearable
                                    type="number"
                                    min="-180"
                                    max="180"
                                    step="any"
                                    label="Longitude (optional)"
                                />
                            </div>
                            <div class="text-caption text-grey-7">
                                Provide both coordinates or leave both empty.
                            </div>
                            <q-separator />
                            <div class="text-h6">First reconstruction</div>
                        </template>
                    </reconstruction-submission-form>
                </q-card-section>
            </q-card>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { useI18n } from 'vue-i18n';
import { computed, ref } from 'vue';
import { useQuasar } from 'quasar';
import { useRouter } from 'vue-router';
import ReconstructionSubmissionForm from 'src/components/ReconstructionSubmissionForm.vue';
import VideoUploadProgress from 'src/components/VideoUploadProgress.vue';
import { type ReconstructionSubmission } from 'src/lib/buildings';
import { useSubmitReconstructionMutation } from 'src/mutations/reconstructions';

const { t } = useI18n();

const router = useRouter();
const quasar = useQuasar();
const name = ref('');
const latitude = ref<number | null>(null);
const longitude = ref<number | null>(null);
const validationError = ref('');
const {
    mutateAsync: submitReconstruction,
    isLoading: submitting,
    errorMessage: submissionError,
    destinationBuildingId,
} = useSubmitReconstructionMutation();
const errorMessage = computed(() => validationError.value || submissionError.value);

async function submit(submission: ReconstructionSubmission): Promise<void> {
    const hasLatitude = typeof latitude.value === 'number' && Number.isFinite(latitude.value);
    const hasLongitude = typeof longitude.value === 'number' && Number.isFinite(longitude.value);
    validationError.value = '';
    if (hasLatitude !== hasLongitude) {
        validationError.value = 'Latitude and longitude must both be set or both be empty.';
        return;
    }

    // Resumable upload through the API upload proxy, then one call that
    // creates the building and schedules the reconstruction. The mutation
    // drives the upload progress shown by VideoUploadProgress.
    await submitReconstruction({
        ...submission,
        buildingId: null,
        building: {
            name: name.value,
            latitude: hasLatitude ? Number(latitude.value) : null,
            longitude: hasLongitude ? Number(longitude.value) : null,
        },
    }).catch(() => undefined);

    const buildingId = destinationBuildingId.value;
    if (buildingId === null) return;
    if (submissionError.value) {
        quasar.notify({
            type: 'negative',
            message: submissionError.value,
        });
    }
    await router.push(`/buildings/${buildingId}`);
}
</script>

<style scoped>
.page-content {
    max-width: 800px;
    margin: 0 auto;
}
</style>
