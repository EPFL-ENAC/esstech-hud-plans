import { useQuery } from '@pinia/colada';
import { computed, onActivated, onDeactivated, ref, type Ref } from 'vue';
import { useDocumentVisibility } from 'src/composables/useDocumentVisibility';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { getUpload, listUploads } from 'src/lib/uploads';

export const MY_UPLOADS_PAGE_SIZE = 20;

function isPermanentErrorCode(statusCode: number): boolean {
    return [401, 403, 404, 422].includes(statusCode);
}

export function useUploadQuery(uploadId: Ref<string>) {
    const subject = getAuthSubject();
    const active = ref(true);
    const visible = useDocumentVisibility();
    const enabled = () => {
        return (
            subject !== null &&
            getAuthSubject() === subject &&
            uploadId.value !== '' &&
            active.value &&
            visible.value
        );
    };

    onActivated(() => {
        active.value = true;
    });
    onDeactivated(() => {
        active.value = false;
    });

    return useQuery({
        key: () => ['uploads', subject, 'detail', uploadId.value],
        enabled,
        query: () => getUpload(uploadId.value),
        staleTime: 5_000,
        refetchOnWindowFocus: true,
        autoRefetch: (state) => {
            if (state.error instanceof ApiError && isPermanentErrorCode(state.error.status)) {
                return false;
            }
            return state.data?.status === 'pending' ? 5_000 : false;
        },
    });
}

export function useMyUploadsQuery(offset: Ref<number>) {
    const subject = getAuthSubject();
    const options = computed(() => ({
        offset: offset.value,
        limit: MY_UPLOADS_PAGE_SIZE + 1,
        sort_order: 'desc' as const,
    }));

    return useQuery({
        key: () => ['uploads', subject, 'list', options.value],
        enabled: () => subject !== null,
        query: () => listUploads(options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });
}

export function useUploadedVideosQuery(offset: Ref<number>, open: Ref<boolean>) {
    const subject = getAuthSubject();
    const options = computed(() => ({
        offset: offset.value,
        limit: MY_UPLOADS_PAGE_SIZE + 1,
        sort_order: 'desc' as const,
        status: 'uploaded' as const,
    }));

    return useQuery({
        key: () => ['uploads', subject, 'list', options.value],
        enabled: () => open.value && subject !== null,
        query: () => listUploads(options.value),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });
}
