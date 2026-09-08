import { i18n } from 'src/i18n/instance';

export interface CaptureLocation {
    latitude: number;
    longitude: number;
    accuracyMeters: number;
    /** Unix timestamp in milliseconds, supplied by the location reading. */
    timestamp: number;
}

export interface RecordedVideo {
    blob: Blob;
    durationSeconds: number;
}

export interface CapturedVideo {
    file: File;
    durationSeconds: number;
    location: CaptureLocation | null;
}

export function toCapturedVideo(
    recording: RecordedVideo,
    location: CaptureLocation | null,
): CapturedVideo {
    const mimeType = recording.blob.type.split(';')[0]?.trim().toLowerCase();
    const extensions: Record<string, string> = {
        'video/webm': 'webm',
        'video/mp4': 'mp4',
        'video/ogg': 'ogv',
        'video/quicktime': 'mov',
        'video/x-matroska': 'mkv',
    };
    const extension = mimeType ? extensions[mimeType] : undefined;
    if (!extension) throw new Error(i18n.global.t('capture.video.recordedFormatUnsupported'));
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    return {
        file: new File([recording.blob], `capture-${timestamp}.${extension}`, {
            type: recording.blob.type,
        }),
        durationSeconds: recording.durationSeconds,
        location,
    };
}
