import { defineRouter } from '#q-app/wrappers';
import {
    createMemoryHistory,
    createRouter,
    createWebHashHistory,
    createWebHistory,
} from 'vue-router';
import routes from './routes';
import { isAuthenticated } from 'src/lib/auth';

/*
 * If not building with SSR mode, you can
 * directly export the Router instantiation;
 *
 * The function below can be async too; either use
 * async/await or return a Promise which resolves
 * with the Router instance.
 */

export default defineRouter(function (/* { store, ssrContext } */) {
    const createHistory = process.env.SERVER
        ? createMemoryHistory
        : process.env.VUE_ROUTER_MODE === 'history'
          ? createWebHistory
          : createWebHashHistory;

    const Router = createRouter({
        scrollBehavior: () => ({ left: 0, top: 0 }),
        routes,

        // Leave this as is and make changes in quasar.conf.js instead!
        // quasar.conf.js -> build -> vueRouterMode
        // quasar.conf.js -> build -> publicPath
        history: createHistory(process.env.VUE_ROUTER_BASE),
    });

    // Redirect unauthenticated users to /login (except on auth routes), and
    // send authenticated users away from the login page.
    Router.beforeEach((to) => {
        // Keycloak strips the fragment from the redirect_uri, so the OAuth
        // response (code, session_state) arrives in window.location.search
        // while the hash router sits at '/' (never on /callback). Detect the
        // inbound response and forward it to /callback as a route query so the
        // exchange runs. This also covers the case where the params end up in
        // the hash by moving them into the query explicitly.
        if (!to.query.code && window.location.search.includes('code=')) {
            const code = new URLSearchParams(window.location.search).get('code') ?? '';
            // Drop the one-time auth code from the address bar.
            window.history.replaceState(null, '', window.location.pathname);
            return { path: '/callback', query: { code } };
        }

        if (to.path === '/callback') {
            return;
        }
        if (to.path === '/login') {
            return isAuthenticated() ? '/' : undefined;
        }
        if (!isAuthenticated()) {
            return '/login';
        }
    });

    return Router;
});
