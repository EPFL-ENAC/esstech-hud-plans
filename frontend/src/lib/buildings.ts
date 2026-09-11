import { i18n } from 'src/i18n/instance';
import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';
import { downloadWithProgress, type FetchProgress } from 'src/lib/utils/fetchProgress';
import { uploadWithProgress } from 'src/lib/utils/xhrUpload';

export interface CurrentUser {
    id: string;
    username: string | null;
    email: string | null;
    name: string | null;
    created_at: string;
    updated_at: string;
}

export interface Building {
    id: string;
    user_id: string;
    name: string;
    address: string | null;
    latitude: number | null;
    longitude: number | null;
    created_at: string;
    updated_at: string;
}

export interface BuildingCreate {
    name: string;
    address?: string | null;
    latitude: number | null;
    longitude: number | null;
}

export type BuildingUpdate = {
    name?: string;
    address?: string | null;
} & (
    { latitude?: never; longitude?: never } | { latitude: number | null; longitude: number | null }
);

export type BuildingSelection =
    { buildingId: string } | { buildingId: null; building: BuildingCreate };

export function isValidBuildingCreate(building: BuildingCreate): boolean {
    const { latitude, longitude } = building;
    if (latitude === null || longitude === null) return latitude === longitude;
    return (
        Number.isFinite(latitude) &&
        latitude >= -90 &&
        latitude <= 90 &&
        Number.isFinite(longitude) &&
        longitude >= -180 &&
        longitude <= 180
    );
}

export interface BuildingFromReconstruction {
    building: Building;
    reconstruction: Reconstruction;
}

export interface BuildingLocation {
    id: string;
    name: string;
    latitude: number;
    longitude: number;
}

export type ReconstructionStatus =
    'preparing' | 'scheduled' | 'running' | 'completed' | 'failed' | 'cancelled' | 'crashed';

export interface ReconstructionSummary {
    id: string;
    status: ReconstructionStatus;
    progress: number; // 0–1
}

export interface BuildingListItem extends Building {
    latest_reconstruction: ReconstructionSummary | null;
}

export interface FfmpegSettings {
    fps: number;
    fit_in_width: number;
    fit_in_height: number;
}

export interface FramePickerWorkflowSettings {
    min_fps: number;
    distance_threshold: number;
    remove_outliers: boolean;
    outlier_sharpness_ratio: number;
}

export interface ColmapWorkflowSettings {
    data_type: 'individual' | 'video' | 'internet';
    quality: 'low' | 'medium' | 'high' | 'extreme';
    camera_model: 'PINHOLE' | 'OPENCV' | 'OPENCV_FISHEYE' | 'RADIAL';
    single_camera: boolean;
    use_gpu: boolean;
    use_global_mapper: boolean;
}

export interface BrushWorkflowSettings {
    total_steps: number;
    render_mode: 'default' | 'mip';
    sh_degree: number;
    max_splats: number;
    refine_every: number;
    growth_grad_threshold: number;
    growth_stop_iter: number;
    max_resolution: number;
    subsample_frames: number;
    alpha_mode: 'masked' | 'transparent';
    export_every: number;
}

export interface SplatGenerationSettings {
    ffmpeg: FfmpegSettings;
    frame_picker: FramePickerWorkflowSettings | null;
    colmap: ColmapWorkflowSettings;
    brush: BrushWorkflowSettings;
}

export interface Reconstruction {
    id: string;
    building_id: string;
    prefect_workflow_id: string | null;
    status: ReconstructionStatus;
    progress: number;
    error_message: string | null;
    settings: SplatGenerationSettings;
    workspace_directory: string | null;
    input_video_path: string | null;
    raw_frames_directory: string | null;
    frames_directory: string | null;
    colmap_directory: string | null;
    splat_path: string | null;
    created_at: string;
    updated_at: string;
}

export interface ReconstructionSubmission {
    video: File;
    settings: SplatGenerationSettings;
}

export class ApiError extends Error {
    constructor(
        message: string,
        readonly status: number,
        readonly body: unknown,
    ) {
        super(message);
    }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await authFetch(`${baseUrl}${path}`, init);
    const text = await response.text();
    let body: unknown = null;
    if (text) {
        try {
            body = JSON.parse(text) as unknown;
        } catch {
            body = text;
        }
    }
    if (!response.ok) {
        throw new ApiError(`Request failed with HTTP ${response.status}`, response.status, body);
    }
    return body as T;
}

export function getCurrentUser(): Promise<CurrentUser> {
    return requestJson('/user/me');
}

export function listBuildingLocations(): Promise<BuildingLocation[]> {
    return requestJson('/buildings/locations');
}

export type ReconstructionStatusFilter = 'processing' | 'idle';

export interface ListBuildingsOptions {
    offset?: number;
    limit?: number;
    sort_order?: 'asc' | 'desc';
    reconstruction_status?: ReconstructionStatusFilter | null;
    search?: string | null;
}

export function listBuildings({
    offset = 0,
    limit = 100,
    sort_order = 'desc',
    reconstruction_status,
    search,
}: ListBuildingsOptions = {}): Promise<BuildingListItem[]> {
    const params = new URLSearchParams({
        offset: String(offset),
        limit: String(limit),
        sort_order,
    });
    if (reconstruction_status != null) {
        params.set('reconstruction_status', reconstruction_status);
    }
    const term = search?.trim() || null;
    if (term !== null) {
        params.set('search', term);
    }
    return requestJson(`/buildings?${params}`);
}

export function createBuilding(payload: BuildingCreate): Promise<Building> {
    return requestJson('/buildings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

export function getBuilding(buildingId: string): Promise<Building> {
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}`);
}

export function updateBuilding(buildingId: string, payload: BuildingUpdate): Promise<Building> {
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

export interface ListReconstructionsOptions {
    offset?: number;
    limit?: number;
    sort_order?: 'asc' | 'desc';
}

export function listReconstructions(
    buildingId: string,
    { offset = 0, limit = 100, sort_order = 'desc' }: ListReconstructionsOptions = {},
): Promise<Reconstruction[]> {
    const params = new URLSearchParams({
        offset: String(offset),
        limit: String(limit),
        sort_order,
    });
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}/reconstructions?${params}`);
}

export function getReconstructionStep(
    buildingId: string,
    reconstructionId: string,
    signal?: AbortSignal | null,
): Promise<string | null> {
    const init: RequestInit = {};
    if (signal !== undefined) init.signal = signal;
    return requestJson(
        `/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/current-step`,
        init,
    );
}

export function cancelReconstruction(
    buildingId: string,
    reconstructionId: string,
): Promise<Reconstruction> {
    return requestJson(
        `/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/cancel`,
        { method: 'POST' },
    );
}

export async function getReconstructionVideo(
    buildingId: string,
    reconstructionId: string,
    signal: AbortSignal,
): Promise<Blob> {
    const response = await authFetch(
        `${baseUrl}/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/video`,
        { signal },
    );
    if (!response.ok) {
        throw new ApiError(
            `Video request failed with HTTP ${response.status}`,
            response.status,
            null,
        );
    }
    return response.blob();
}

export async function getReconstructionSplat(
    buildingId: string,
    reconstructionId: string,
    signal: AbortSignal,
    onProgress?: (progress: FetchProgress) => void,
): Promise<ArrayBuffer> {
    return downloadWithProgress(
        `${baseUrl}/buildings/${encodeURIComponent(buildingId)}/reconstructions/${encodeURIComponent(reconstructionId)}/splat`,
        { signal },
        onProgress,
    );
}

async function uploadJson<T>(
    path: string,
    body: FormData,
    onProgress?: (progress: FetchProgress) => void,
): Promise<T> {
    const { status, text } = await uploadWithProgress(`${baseUrl}${path}`, body, onProgress);
    let parsed: unknown = null;
    if (text) {
        try {
            parsed = JSON.parse(text) as unknown;
        } catch {
            parsed = text;
        }
    }
    if (status < 200 || status >= 300) {
        throw new ApiError(`Request failed with HTTP ${status}`, status, parsed);
    }
    return parsed as T;
}

export function createReconstruction(
    buildingId: string,
    submission: ReconstructionSubmission,
    onProgress?: (progress: FetchProgress) => void,
): Promise<Reconstruction> {
    const formData = new FormData();
    formData.append('file', submission.video);
    formData.append('settings', JSON.stringify(submission.settings));
    return uploadJson(
        `/buildings/${encodeURIComponent(buildingId)}/reconstructions`,
        formData,
        onProgress,
    );
}

export function createBuildingFromReconstruction(
    building: BuildingCreate,
    submission: ReconstructionSubmission,
    onProgress?: (progress: FetchProgress) => void,
): Promise<BuildingFromReconstruction> {
    const formData = new FormData();
    formData.append('file', submission.video);
    formData.append('building', JSON.stringify(building));
    formData.append('settings', JSON.stringify(submission.settings));
    return uploadJson('/buildings/from-reconstruction', formData, onProgress);
}

export function getFailedBuildingId(error: unknown): string | null {
    if (!(error instanceof ApiError) || !isRecord(error.body)) return null;
    const detail = error.body.detail;
    if (!isRecord(detail) || typeof detail.building_id !== 'string') return null;
    return detail.building_id;
}

export function getReconstructionSubmissionErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = isRecord(error.body) ? error.body.detail : null;
        if (typeof detail === 'string') return detail;
        if (isRecord(detail) && typeof detail.message === 'string') return detail.message;
        if (error.status === 422) return i18n.global.t('reconstructions.errors.invalidSettings');
        if (error.status === 401) return i18n.global.t('reconstructions.errors.sessionExpired');
        if (error.status === 404)
            return i18n.global.t('reconstructions.errors.buildingUnavailable');
        return i18n.global.t('reconstructions.errors.submitFailed');
    }
    return i18n.global.t('errors.connection');
}

export function getFailedReconstructionId(error: unknown): string | null {
    if (!(error instanceof ApiError) || !isRecord(error.body)) return null;
    const detail = error.body.detail;
    if (!isRecord(detail) || typeof detail.reconstruction_id !== 'string') return null;
    return detail.reconstruction_id;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
}
