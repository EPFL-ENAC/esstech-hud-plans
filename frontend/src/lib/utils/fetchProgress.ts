export interface FetchProgress {
    loaded: number; // bytes
    total: number; // bytes
}

export function formatMb(bytes: number): string {
    if (bytes <= 0) return '0';
    return (bytes / 1024 / 1024).toFixed(1);
}
