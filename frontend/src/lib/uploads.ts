import { requestJson } from 'src/lib/api';

export type UploadStatus = 'pending' | 'uploaded' | 'failed';

export interface UserUpload {
    id: string;
    user_id: string;
    name: string;
    description: string;
    filename: string;
    size_bytes: number;
    uploaded_bytes: number;
    status: UploadStatus;
    created_at: string;
    uploaded_at: string | null;
}

export interface ListUploadsOptions {
    offset?: number;
    limit?: number;
    sort_order?: 'asc' | 'desc';
}

export function getUpload(uploadId: string): Promise<UserUpload> {
    return requestJson(`/uploads/${encodeURIComponent(uploadId)}`);
}

export function listUploads({
    offset = 0,
    limit = 100,
    sort_order = 'desc',
}: ListUploadsOptions = {}): Promise<UserUpload[]> {
    const params = new URLSearchParams({
        offset: String(offset),
        limit: String(limit),
        sort_order,
    });
    return requestJson(`/uploads?${params}`);
}
