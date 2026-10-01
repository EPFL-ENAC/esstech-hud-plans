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

            <q-card flat bordered>
                <q-card-section>
                    <div class="q-gutter-y-md">
                        <div class="text-h6">First reconstruction</div>
                        <q-file
                            v-model="videoFile"
                            outlined
                            accept="video/*"
                            label="Video file"
                            clearable
                            :disable="uploading"
                        >
                            <template #prepend><q-icon name="movie" /></template>
                        </q-file>

                        <reconstruction-settings v-model="settings" />

                        <video-upload-progress v-if="uploading" />

                        <q-btn
                            color="primary"
                            icon="upload"
                            label="Start uploading"
                            :disable="videoFile === null || uploading || uploadId !== null"
                            :loading="uploading"
                            @click="startUpload"
                        />
                    </div>
                </q-card-section>
            </q-card>

            <q-card flat bordered :disable="!buildingEnabled">
                <q-card-section>
                    <div class="q-gutter-y-md">
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
                    </div>
                </q-card-section>
            </q-card>

            <q-btn
                v-if="buildingEnabled"
                color="primary"
                icon="check_circle"
                label="Create reconstruction"
                :disable="!canCreate || creating"
                :loading="creating"
                @click="create"
            />
        </div>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import { useI18n } from 'vue-i18n';
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { useRouter } from 'vue-router';
import ReconstructionSettings from 'src/components/ReconstructionSettings.vue';
import VideoUploadProgress from 'src/components/VideoUploadProgress.vue';
import { ApiError } from 'src/lib/buildings';
import { uploadVideoResumable } from 'src/lib/utils/tusUpload';
import {
    isValidReconstructionSettings,
    makeDefaultReconstructionSettings,
    toSplatGenerationSettings,
} from 'src/lib/reconstruction-settings';
import { useCreateReconstructionMutation } from 'src/mutations/reconstructions';
import { useVideoUploadStore } from 'src/stores/videoUpload';

const { t } = useI18n();

const router = useRouter();
const quasar = useQuasar();
const name = ref('');
const latitude = ref<number | null>(null);
const longitude = ref<number | null>(null);
const validationError = ref('');
const videoFile = ref<File | null>(null);
const settings = ref(makeDefaultReconstructionSettings());
const uploading = ref(false);
/** tusd-side id of the finished video upload; non-null only after success. */
const uploadId = ref<string | null>(null);
const uploadError = ref('');
const {
    mutateAsync: createReconstruction,
    isLoading: creating,
    errorMessage: createError,
    destinationBuildingId,
} = useCreateReconstructionMutation();
const errorMessage = computed(
    () => validationError.value || uploadError.value || createError.value,
);

// The building section unlocks when the upload starts, so the info can be
// filled while the video transfers; it locks again after a failed upload.
const buildingEnabled = computed(() => uploading.value || uploadId.value !== null);
const canCreate = computed(
    () => uploadId.value !== null && isValidReconstructionSettings(settings.value),
);

// Picking a different file invalidates the finished upload.
watch(videoFile, () => {
    if (uploadId.value !== null) {
        uploadId.value = null;
        uploadError.value = '';
    }
});

async function startUpload(): Promise<void> {
    if (videoFile.value === null) return;
    const videoUpload = useVideoUploadStore();
    videoUpload.reset();
    uploadError.value = '';
    uploading.value = true;
    try {
        // Resumable upload through the API upload proxy, which forwards to
        // tusd and reports true network bytes; the finished upload is
        // submitted for scheduling by Create reconstruction.
        const result = await uploadVideoResumable(videoFile.value, {
            onProgress: videoUpload.update,
            onResumed: () => videoUpload.setResumed(true),
        });
        // The upload step is done; the caption must not claim a resumed
        // upload during the later creation call.
        videoUpload.setResumed(false);
        uploadId.value = result.uploadId;
    } catch (error) {
        if (error instanceof ApiError) {
            uploadError.value =
                error.status === 401 ? t('reconstructions.errors.sessionExpired') : error.message;
        } else {
            uploadError.value = t('errors.connection');
        }
    } finally {
        uploading.value = false;
    }
}

async function create(): Promise<void> {
    if (uploadId.value === null) return;
    const hasLatitude = typeof latitude.value === 'number' && Number.isFinite(latitude.value);
    const hasLongitude = typeof longitude.value === 'number' && Number.isFinite(longitude.value);
    validationError.value = '';
    if (hasLatitude !== hasLongitude) {
        validationError.value = 'Latitude and longitude must both be set or both be empty.';
        return;
    }

    // The video is already uploaded; one call creates the building and
    // schedules the reconstruction from the finished upload.
    await createReconstruction({
        uploadId: uploadId.value,
        buildingId: null,
        building: {
            name: name.value,
            latitude: hasLatitude ? Number(latitude.value) : null,
            longitude: hasLongitude ? Number(longitude.value) : null,
        },
        settings: toSplatGenerationSettings(settings.value),
    }).catch(() => undefined);

    const buildingId = destinationBuildingId.value;
    if (buildingId === null) return;
    if (createError.value) {
        quasar.notify({
            type: 'negative',
            message: createError.value,
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
