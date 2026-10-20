import { defineBoot } from '#q-app/wrappers';
import { PiniaColada } from '@pinia/colada';
import { PiniaColadaAutoRefetch } from '@pinia/colada-plugin-auto-refetch';

export default defineBoot(({ app }) => {
    app.use(PiniaColada, {
        plugins: [PiniaColadaAutoRefetch()],
    });
});
