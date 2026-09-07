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
            // Real tab pages. They render in the main (default) view and are
            // kept alive so their state survives opening a detail drawer.
            {
                path: 'home',
                name: 'home',
                meta: { tab: true },
                component: () => import('pages/HomePage.vue'),
            },
            {
                path: 'capture',
                name: 'capture',
                meta: { tab: true },
                component: () => import('pages/CapturePage.vue'),
            },
            {
                path: 'library',
                name: 'library',
                meta: { tab: true },
                component: () => import('pages/LibraryPage.vue'),
            },
            {
                path: 'more',
                name: 'more',
                meta: { tab: true },
                component: () => import('pages/MorePage.vue'),
            },

            // Detail pages. These open in the right drawer over the current
            // tab page (BackgroundPage keeps the underlying page mounted).
            // They live outside /library so a building is not a "child" of the
            // Library page.
            {
                path: 'building/:id',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/BuildingPage.vue'),
                },
            },
            {
                path: 'building/:id/plan/2d',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/Plan2DPage.vue'),
                },
            },
            {
                path: 'building/:id/plan/3d',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/Plan3DPage.vue'),
                },
            },
            {
                path: 'building/:id/data',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/BuildingDataPage.vue'),
                },
            },
            {
                path: 'capture/video',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/CaptureVideoPage.vue'),
                },
            },
            {
                path: 'capture/new',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/NewCapturePage.vue'),
                },
            },
            {
                path: 'capture/processing/:id',
                meta: { drawer: true },
                components: {
                    default: () => import('components/BackgroundPage.vue'),
                    detail: () => import('pages/ProcessingPage.vue'),
                },
            },

            {
                path: '/admin',
                component: () => import('pages/AdminPage.vue'),
            },
        ],
    },

    // Splat viewer: its own full-screen page plus a left pipeline drawer
    // (named view "drawer"). Uses a dedicated layout so the main navigation
    // drawer and footer do not affect it.
    {
        path: '/splat/:id',
        component: () => import('layouts/SplatLayout.vue'),
        children: [
            {
                path: '',
                components: {
                    default: () => import('pages/SplatPage.vue'),
                    drawer: () => import('src/drawers/SplatPipelineDrawer.vue'),
                },
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
