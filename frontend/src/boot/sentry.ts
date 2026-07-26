import { defineBoot } from '#q-app/wrappers';
import * as Sentry from '@sentry/vue';

interface CustomWindow extends Window {
    env: {
        SENTRY_ENVIRONMENT?: string;
        SENTRY_RATE?: string;
    };
}

export default defineBoot(({ app }) => {
    const appEnv = (window as unknown as CustomWindow).env;

    Sentry.init({
        app,
        dsn: 'https://aa1211ccc1774558b5b43b4e0e5ebc10@enac-it-glitchtip.epfl.ch/2',
        environment: appEnv.SENTRY_ENVIRONMENT ?? 'production',
        tracesSampleRate: parseFloat(appEnv.SENTRY_RATE ?? '1.00'), // 100% of transactions — adjust to your needs
    });
});
