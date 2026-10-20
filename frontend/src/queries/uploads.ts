import { useQuery } from '@pinia/colada';
import { computed, onActivated, onDeactivated, ref, watch, type Ref } from 'vue';
import { useDocumentVisibility } from 'src/composables/useDocumentVisibility';
import { ApiError } from 'src/lib/api';
import { getAuthSubject } from 'src/lib/auth';
import { getUpload, listUploads, type UserUpload } from 'src/lib/uploads';

export const MY_UPLOADS_PAGE_SIZE = 20;

function isPermanentErrorCode(statusCode: number): boolean {
    return [401, 403, 404, 422].includes(statusCode);
}

function hasPendingUploadsOnPage(uploads: UserUpload[] | undefined): boolean {
    return (
        uploads?.slice(0, MY_UPLOADS_PAGE_SIZE).some((upload) => upload.status === 'pending') ===
        true
    );
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
    const active = ref(true);
    const visible = useDocumentVisibility();
    const enabled = () =>
        subject !== null && getAuthSubject() === subject && active.value && visible.value;
    const options = computed(() => ({
        offset: offset.value,
        limit: MY_UPLOADS_PAGE_SIZE + 1,
        sort_order: 'desc' as const,
    }));

    onActivated(() => {
        active.value = true;
    });
    onDeactivated(() => {
        active.value = false;
    });

    const query = useQuery({
        key: () => ['uploads', subject, 'list', options.value],
        enabled,
        query: () => listUploads(options.value),
        staleTime: 5_000,
        refetchOnWindowFocus: true,
        autoRefetch: (state) => {
            if (state.error instanceof ApiError && isPermanentErrorCode(state.error.status)) {
                return false;
            }
            return hasPendingUploadsOnPage(state.data) ? 5_000 : false;
        },
    });

    watch(
        [options, enabled],
        () => {
            // A poll that finishes off-page leaves no timer for a fresh cached entry.
            if (enabled() && !query.isLoading.value && hasPendingUploadsOnPage(query.data.value)) {
                void query.refetch();
            }
        },
        { immediate: true, flush: 'post' },
    );

    return query;
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
