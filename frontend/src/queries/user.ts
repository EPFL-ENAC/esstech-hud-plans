import { useQuery } from '@pinia/colada';
import { getAuthSubject } from 'src/lib/auth';
import { getCurrentUser } from 'src/lib/buildings';

export function useCurrentUserQuery() {
    const subject = getAuthSubject();

    return useQuery({
        key: ['current-user', subject],
        enabled: () => subject !== null,
        query: getCurrentUser,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    });
}
