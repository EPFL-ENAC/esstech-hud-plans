import { defineBoot } from '#q-app/wrappers';
import { PiniaColada } from '@pinia/colada';

export default defineBoot(({ app }) => {
    app.use(PiniaColada);
});
