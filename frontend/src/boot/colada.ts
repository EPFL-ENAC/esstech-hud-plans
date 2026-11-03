import { defineBoot } from '#q-app/wrappers';
import { PiniaColada } from '@pinia/colada';
import { PiniaColadaAutoRefetch } from '@pinia/colada-plugin-auto-refetch';
import { PiniaColadaDownloadProgress } from 'src/queries/downloadProgress';

export default defineBoot(({ app }) => {
    app.use(PiniaColada, {
        plugins: [PiniaColadaAutoRefetch(), PiniaColadaDownloadProgress()],
    });
});
