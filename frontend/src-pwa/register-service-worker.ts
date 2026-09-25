import { register } from 'register-service-worker';

// No forced activation or reload: recordings/forms live in memory. The waiting
// worker takes over only after all windows controlled by the old worker close.
register(process.env.SERVICE_WORKER_FILE, {
    error(error: Error) {
        // Installation failure must not prevent normal online browser use.
        console.error('HUD Plans service worker registration failed:', error);
    },
});
