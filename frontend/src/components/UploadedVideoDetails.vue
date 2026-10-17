<template>
    <q-card flat bordered class="selected-upload">
        <q-card-section class="row items-center no-wrap q-gutter-md">
            <q-icon name="video_library" size="sm" color="primary" />
            <div class="col upload-text">
                <div class="text-weight-medium">{{ upload.filename }}</div>
                <div v-if="upload.name.trim() && upload.name !== 'TODO'">{{ upload.name }}</div>
                <div class="text-caption text-grey-7">
                    {{ formatFileSize(upload.size_bytes, locale) }}
                    · {{ t('uploads.uploaded', { date: uploadedDate }) }}
                </div>
            </div>
            <q-btn
                flat
                round
                icon="close"
                :aria-label="t('capture.video.clear')"
                :disable="disable"
                @click="emit('clear')"
            />
        </q-card-section>
    </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { UserUpload } from 'src/lib/uploads';
import { formatFileSize } from 'src/lib/utils/formatFileSize';

const props = defineProps<{ upload: UserUpload; disable?: boolean }>();
const emit = defineEmits<{ clear: [] }>();
const { t, locale } = useI18n();
const uploadedDate = computed(() =>
    new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(
        new Date(props.upload.uploaded_at ?? props.upload.created_at),
    ),
);
</script>

<style scoped>
.upload-text {
    min-width: 0;
    overflow-wrap: anywhere;
}
</style>
