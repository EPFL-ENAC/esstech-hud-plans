export type CameraSide = 'front' | 'rear';

export interface CameraOption {
    label: string;
    value: string;
    side: CameraSide | null;
}

export function detectCameraSide(device: MediaDeviceInfo): CameraSide | null {
    try {
        const modes = (device as InputDeviceInfo).getCapabilities?.().facingMode;
        if (modes?.length !== 1) return null;
        if (modes[0] === 'user') return 'front';
        if (modes[0] === 'environment') return 'rear';
    } catch {
        // Unavailable capabilities leave the camera unclassified.
    }
    return null;
}
