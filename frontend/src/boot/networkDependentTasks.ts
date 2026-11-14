import { defineBoot } from '#q-app/wrappers';
import { useNetworkDependentTasks } from 'src/stores/networkDependentTasks';

export default defineBoot(({ store }) => {
    const tasks = useNetworkDependentTasks(store);
    if (import.meta.hot) {
        import.meta.hot.dispose(() => tasks.$dispose());
    }
});
