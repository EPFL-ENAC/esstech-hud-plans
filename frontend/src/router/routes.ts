import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
    {
        path: '/',
        component: () => import('layouts/MainLayout.vue'),
        children: [
            {
                path: '',
                redirect: '/home',
            },
            {
                path: 'home',
                component: () => import('pages/HomePage.vue'),
            },
            {
                path: 'capture',
                component: () => import('pages/CapturePage.vue'),
            },
            {
                path: 'capture/video',
                component: () => import('pages/CaptureVideoPage.vue'),
            },
            {
                path: 'capture/new',
                component: () => import('pages/NewCapturePage.vue'),
            },
            {
                path: 'capture/processing/:id',
                component: () => import('pages/ProcessingPage.vue'),
            },
            {
                path: 'library',
                component: () => import('pages/LibraryPage.vue'),
            },
            {
                path: 'library/building/:id',
                component: () => import('pages/BuildingPage.vue'),
            },
            {
                path: 'library/building/:id/plan/2d',
                component: () => import('pages/Plan2DPage.vue'),
            },
            {
                path: 'library/building/:id/plan/3d',
                component: () => import('pages/Plan3DPage.vue'),
            },
            {
                path: 'library/building/:id/data',
                component: () => import('pages/BuildingDataPage.vue'),
            },
            {
                path: 'more',
                component: () => import('pages/MorePage.vue'),
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
        ],
    },

    // Advanced pipeline page, using its own duplicate layout (no tab bar)
    {
        path: '/advanced',
        component: () => import('layouts/AdvancedLayout.vue'),
        children: [
            {
                path: '',
                component: () => import('pages/AdvancedPage.vue'),
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
