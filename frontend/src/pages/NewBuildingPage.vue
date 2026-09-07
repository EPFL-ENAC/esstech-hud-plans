<template>
    <q-page class="q-pa-md">
        <div class="page-content q-gutter-y-md">
            <div class="row items-center q-gutter-sm">
                <q-btn flat round icon="arrow_back" aria-label="Back" to="/buildings" />
                <div>
                    <h1 class="text-h5 q-my-none">New building reconstruction</h1>
                    <div class="text-caption text-grey-7">
                        Create a building and schedule its first reconstruction.
                    </div>
                </div>
            </div>

            <q-banner v-if="errorMessage" rounded class="bg-red-1 text-negative">
                {{ errorMessage }}
            </q-banner>

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
import { ref } from 'vue';
import { useQuasar } from 'quasar';
import { useRouter } from 'vue-router';
import ReconstructionSubmissionForm from 'src/components/ReconstructionSubmissionForm.vue';
import {
    type ReconstructionSubmission,
    createBuilding,
    createReconstruction,
    getFailedReconstructionId,
} from 'src/lib/buildings';

const router = useRouter();
const quasar = useQuasar();
const name = ref('');
const latitude = ref<number | null>(null);
const longitude = ref<number | null>(null);
const submitting = ref(false);
const errorMessage = ref('');

async function submit(submission: ReconstructionSubmission): Promise<void> {
    const hasLatitude = typeof latitude.value === 'number' && Number.isFinite(latitude.value);
    const hasLongitude = typeof longitude.value === 'number' && Number.isFinite(longitude.value);
    if (hasLatitude !== hasLongitude) {
        errorMessage.value = 'Latitude and longitude must both be set or both be empty.';
        return;
    }

    submitting.value = true;
    errorMessage.value = '';
    let buildingId: string | null = null;
    try {
        const building = await createBuilding({
            name: name.value,
            latitude: hasLatitude ? Number(latitude.value) : null,
            longitude: hasLongitude ? Number(longitude.value) : null,
        });
        buildingId = building.id;
        await createReconstruction(building.id, submission);
        await router.push(`/buildings/${building.id}`);
    } catch (error) {
        if (buildingId) {
            const failedId = getFailedReconstructionId(error);
            quasar.notify({
                type: 'negative',
                message: failedId
                    ? `Reconstruction ${failedId} could not be scheduled.`
                    : 'The building was created, but reconstruction submission failed.',
            });
            await router.push(`/buildings/${buildingId}`);
        } else {
            errorMessage.value = error instanceof Error ? error.message : String(error);
        }
    } finally {
        submitting.value = false;
    }
}
</script>

<style scoped>
.page-content {
    max-width: 800px;
    margin: 0 auto;
}
</style>
