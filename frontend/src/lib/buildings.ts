import { baseUrl } from 'boot/api';
import { authFetch } from 'src/lib/auth';

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
    latitude: number | null;
    longitude: number | null;
    created_at: string;
    updated_at: string;
}

export type ReconstructionStatus =
    | 'preparing'
    | 'scheduled'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'crashed';

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

export function listBuildings(): Promise<Building[]> {
    return requestJson('/buildings');
}

export function createBuilding(payload: {
    name: string;
    latitude: number | null;
    longitude: number | null;
}): Promise<Building> {
    return requestJson('/buildings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

export function getBuilding(buildingId: string): Promise<Building> {
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}`);
}

export function listReconstructions(buildingId: string): Promise<Reconstruction[]> {
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}/reconstructions`);
}

export function createReconstruction(
    buildingId: string,
    submission: ReconstructionSubmission,
): Promise<Reconstruction> {
    const formData = new FormData();
    formData.append('file', submission.video);
    formData.append('settings', JSON.stringify(submission.settings));
    return requestJson(`/buildings/${encodeURIComponent(buildingId)}/reconstructions`, {
        method: 'POST',
        body: formData,
    });
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
