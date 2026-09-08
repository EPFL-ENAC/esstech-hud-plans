export interface RecordedVideo {
    blob: Blob;
    durationSeconds: number;
}

export interface CapturedVideo {
    file: File;
    durationSeconds: number;
}

export function toCapturedVideo(recording: RecordedVideo): CapturedVideo {
    const mimeType = recording.blob.type.split(';')[0]?.trim().toLowerCase();
    const extensions: Record<string, string> = {
        'video/webm': 'webm',
        'video/mp4': 'mp4',
        'video/ogg': 'ogv',
        'video/quicktime': 'mov',
        'video/x-matroska': 'mkv',
    };
    const extension = mimeType ? extensions[mimeType] : undefined;
    if (!extension) throw new Error('The recorded video format is not supported.');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    return {
        file: new File([recording.blob], `capture-${timestamp}.${extension}`, {
            type: recording.blob.type,
        }),
        durationSeconds: recording.durationSeconds,
    };
}
