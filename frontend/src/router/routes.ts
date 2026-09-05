import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
    {
        path: '/',
        component: () => import('layouts/MainLayout.vue'),
        children: [
            {
                path: '',
                component: () => import('pages/IndexPage.vue'),
            },
            {
                path: '/splat/:id',
                components: {
                    default: () => import('pages/SplatPage.vue'),
                    drawer: () => import('src/drawers/SplatPipelineDrawer.vue'),
                },
            },
            {
                path: '/admin',
                component: () => import('pages/AdminPage.vue'),
            },
            {
                // Temporary developer route for testing the workflows API.
                path: '/workflow-test',
                component: () => import('pages/WorkflowTestPage.vue'),
            },
        ],
    },

    // Auth routes, outside the main layout (no header/drawer)
    {
        path: '/login',
        component: () => import('pages/LoginPage.vue'),
    },
    {
        path: '/callback',
        component: () => import('pages/CallbackPage.vue'),
    },

    // Always leave this as last one,
    // but you can also remove it
    {
        path: '/:catchAll(.*)*',
        component: () => import('pages/ErrorNotFound.vue'),
    },
];

export default routes;
