import type { CaptureLocation } from './captured-video';

/** Request one fresh location; location failures must not prevent using the video. */
export function getCaptureLocation(): Promise<CaptureLocation | null> {
    return new Promise((resolve) => {
        try {
            if (typeof navigator === 'undefined' || !navigator.geolocation) {
                resolve(null);
                return;
            }

            navigator.geolocation.getCurrentPosition(
                ({ coords, timestamp }) => {
                    resolve({
                        latitude: coords.latitude,
                        longitude: coords.longitude,
                        accuracyMeters: coords.accuracy,
                        timestamp,
                    });
                },
                () => resolve(null),
                { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
            );
        } catch {
            resolve(null);
        }
    });
}
