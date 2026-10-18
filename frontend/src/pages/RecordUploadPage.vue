<template>
    <video-recorder
        :busy="returning"
        :recording-disabled="submitted"
        :error-message="errorMessage"
        @recorded="uploadRecording"
        @discard="openUploads"
    >
        <template #error-actions>
            <q-btn
                v-if="submitted"
                flat
                no-caps
                :label="t('uploads.new.viewUploads')"
                :loading="returning"
                @click="openUploads"
            />
        </template>
    </video-recorder>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useQuasar } from 'quasar';
import VideoRecorder from 'src/components/VideoRecorder.vue';
import { getAuthSubject } from 'src/lib/auth';
import { type RecordedVideo, toCapturedVideo } from 'src/lib/captured-video';
import { useUploadVideoMutation } from 'src/mutations/uploads';

const router = useRouter();
const { t } = useI18n();
const $q = useQuasar();
const subject = getAuthSubject();
const { mutateAsync } = useUploadVideoMutation();

const submitted = ref(false);
const returning = ref(false);
const errorMessage = ref('');

async function uploadRecording(recording: RecordedVideo): Promise<void> {
    if (submitted.value || returning.value) return;

    errorMessage.value = '';
    let file: File;
    try {
        file = toCapturedVideo(recording, null).file;
    } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : t('capture.openFailed');
        return;
    }

    submitted.value = true;
    // The transfer and its completion handler outlive this page.
    void uploadInBackground(file);
    await openUploads();
}

async function uploadInBackground(file: File): Promise<void> {
    try {
        await mutateAsync({ file });
    } catch {
        if (subject !== null && getAuthSubject() === subject) {
            $q.notify({
                type: 'negative',
                message: t('uploads.record.failed', { filename: file.name }),
            });
        }
        return;
    }

    if (subject !== null && getAuthSubject() === subject) {
        $q.notify({
            type: 'positive',
            message: t('uploads.new.completed', { filename: file.name }),
        });
    }
}

async function openUploads(): Promise<void> {
    if (returning.value) return;

    returning.value = true;
    errorMessage.value = '';
    try {
        const failure = await router.replace({ name: 'uploads' });
        if (failure) errorMessage.value = t('uploads.record.navigationFailed');
    } catch {
        errorMessage.value = t('uploads.record.navigationFailed');
    } finally {
        returning.value = false;
    }
}
</script>
