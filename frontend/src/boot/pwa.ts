import { defineBoot } from '#q-app/wrappers';
import { usePwaInstallStore } from 'src/stores/pwaInstall';

export default defineBoot(({ store }) => {
    const pwaInstall = usePwaInstallStore(store);
    pwaInstall.startTracking();
    if (import.meta.hot) import.meta.hot.dispose(() => pwaInstall.stopTracking());
});
