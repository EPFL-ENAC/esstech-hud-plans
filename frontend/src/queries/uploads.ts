import { useQuery } from '@pinia/colada';
import { computed, type Ref } from 'vue';
import { getAuthSubject } from 'src/lib/auth';
import { listUploads } from 'src/lib/uploads';

export const MY_UPLOADS_PAGE_SIZE = 20;

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
