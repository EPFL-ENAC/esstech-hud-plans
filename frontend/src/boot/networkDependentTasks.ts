import { defineBoot } from '#q-app/wrappers';
import { useNetworkDependentTasks } from 'src/stores/networkDependentTasks';

export default defineBoot(async ({ store }) => {
    const tasks = useNetworkDependentTasks(store);
    await tasks.initialize();
    if (import.meta.hot) {
        import.meta.hot.dispose(() => tasks.$dispose());
    }
});
