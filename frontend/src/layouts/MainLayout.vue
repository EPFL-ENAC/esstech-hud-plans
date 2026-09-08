<template>
    <q-layout view="hhh Lpr lFf" class="app-layout">
        <q-page-container>
            <router-view v-slot="{ Component, route }">
                <keep-alive :include="['HomePage', 'CapturePage', 'LibraryPage', 'MorePage']">
                    <component :is="Component" :key="route.path" />
                </keep-alive>
            </router-view>
        </q-page-container>

        <!-- Footer tab bar: mobile only. On desktop (md and up) navigation
             moves to the left drawer below, always visible. -->
        <q-footer v-if="$q.screen.lt.md" bordered class="bg-white footer-tabs">
            <q-tabs
                no-caps
                align="justify"
                active-color="primary"
                indicator-color="transparent"
                class="text-grey-7"
            >
                <q-route-tab to="/home" icon="home" :label="t('navigation.home')" />
                <q-route-tab to="/capture" icon="photo_camera" :label="t('navigation.capture')" />
                <q-route-tab to="/library" icon="list" :label="t('navigation.library')" />
                <q-route-tab to="/more" icon="more_horiz" :label="t('navigation.more')" />
            </q-tabs>
        </q-footer>

        <!-- Left navigation drawer: desktop only. Always visible on medium
             screens and up (show-if-above) and cannot be hidden; absent on
             mobile, where the footer tab bar is used instead. -->
        <q-drawer side="left" show-if-above :breakpoint="1024" bordered :width="navWidth">
            <div class="q-pa-md text-subtitle2 text-weight-medium text-grey-8">
                {{ t('navigation.title') }}
            </div>
            <q-list padding>
                <q-item clickable v-ripple :to="'/home'">
                    <q-item-section avatar>
                        <q-icon name="home" />
                    </q-item-section>
                    <q-item-section>{{ t('navigation.home') }}</q-item-section>
                </q-item>
                <q-item clickable v-ripple :to="'/capture'">
                    <q-item-section avatar>
                        <q-icon name="photo_camera" />
                    </q-item-section>
                    <q-item-section>{{ t('navigation.capture') }}</q-item-section>
                </q-item>
                <q-item clickable v-ripple :to="'/library'">
                    <q-item-section avatar>
                        <q-icon name="list" />
                    </q-item-section>
                    <q-item-section>{{ t('navigation.library') }}</q-item-section>
                </q-item>
                <q-item clickable v-ripple :to="'/more'">
                    <q-item-section avatar>
                        <q-icon name="more_horiz" />
                    </q-item-section>
                    <q-item-section>{{ t('navigation.more') }}</q-item-section>
                </q-item>
            </q-list>
        </q-drawer>

        <!-- Right drawer: detail pages. Full screen width on medium sized
             screens and smaller, and it stops above the footer so the footer
             tab bar stays visible. -->
        <q-drawer
            :model-value="detailOpen"
            side="right"
            overlay
            :bordered="!$q.screen.lt.md"
            :width="detailWidth"
            :breakpoint="0"
            :style="$q.screen.lt.md ? { bottom: 'var(--footer-height)' } : undefined"
            @update:model-value="onDetailChanged"
        >
            <!-- q-page (used by the detail pages) requires a
                 q-page-container ancestor. -->
            <q-page-container>
                <router-view name="detail" />
            </q-page-container>
        </q-drawer>
    </q-layout>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { useQuasar } from 'quasar';
import { useRoute, useRouter } from 'vue-router';
import { useUiStore, type BackgroundPageName } from 'src/stores/ui';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const route = useRoute();
const router = useRouter();
const $q = useQuasar();
const ui = useUiStore();

// Left navigation drawer width, used on desktop (md and up) only.
const navWidth = 220;

// Right drawer hosts detail pages; it is controlled by the active route.
const detailOpen = ref(false);
watch(
    () => route.meta.drawer === true,
    (open) => {
        detailOpen.value = open;
    },
    { immediate: true },
);

// Full screen width on medium sized screens and smaller; a fixed width on
// larger screens (md and up). Uses the Quasar screen utility so the drawer
// never exceeds the viewport width.
const detailWidth = computed(() => ($q.screen.lt.md ? $q.screen.width : 650));

// A controlled QDrawer emits update:model-value=false internally on any route
// change (Quasar hides drawers on route change, and it has no noRouteDismiss
// prop). We must ignore those spurious closes and only react to a genuine
// user close (swipe/back) which happens with no recent navigation.
let lastNavAt = 0;

// Remember which real tab page the user is on, so detail pages can keep it
// as their background.
watch(
    () => route.path,
    () => {
        lastNavAt = Date.now();
        if (route.meta.tab === true) {
            ui.setBackground(route.name as BackgroundPageName);
        }
    },
    { immediate: true },
);

// Reflect drawer changes. Closing returns to the underlying background page
// so the route stays in sync with the drawer.
function onDetailChanged(opened: boolean) {
    if (opened === true) {
        detailOpen.value = true;
        return;
    }
    // A close that arrives right after a route change was triggered by Quasar
    // hiding the drawer on navigation (building -> 2d/3d plan), not by the
    // user. Ignore it so the drawer stays open.
    if (Date.now() - lastNavAt < 300) {
        return;
    }
    closeDrawer();
}

// Programmatic close of the right drawer. Returns to the underlying
// background page so the route stays in sync with the closed drawer.
function closeDrawer() {
    detailOpen.value = false;
    if (route.meta.drawer === true) {
        void router.push(`/${ui.background}`);
    }
}

// A click that should not close the drawer: one inside the drawer itself,
// or one on a link / other interactive element, which should keep its
// normal behaviour (routing) instead.
function clickShouldKeepDrawer(evt: MouseEvent): boolean {
    const target = evt.target as Element | null;
    if (target === null) {
        return false;
    }
    const drawer = document.querySelector('.q-drawer--right');
    if (drawer?.contains(target) === true) {
        return true;
    }
    return (
        target.closest('a, button, [role="button"], .q-item--clickable, .q-tab, .q-btn') !== null
    );
}

// Close the right drawer when the user clicks on an empty region outside
// it (e.g. the underlying page or the left navigation drawer padding).
// Clicks on links or list items are left to their usual routing behaviour.
// No backdrop is shown, so the left navigation drawer stays fully usable.
//
// Uses the capture phase on purpose: navigation (e.g. to a nested 2d/3d plan
// page) re-renders the drawer content and detaches the clicked element from
// the DOM. A bubbling handler would then fail its containment check against
// the now-detached target and wrongly close the drawer. Capture runs at the
// document before any target handler can navigate, so the clicked element is
// still attached and the check stays reliable.
function onDocClick(evt: MouseEvent) {
    if (detailOpen.value !== true || clickShouldKeepDrawer(evt)) {
        return;
    }
    closeDrawer();
}

onMounted(() => document.addEventListener('click', onDocClick, true));
onBeforeUnmount(() => document.removeEventListener('click', onDocClick, true));
</script>

<style scoped>
/* Shared footer height so the right drawer stops above the tab bar.
   Matches how high the footer actually renders (tab min-height + border). */
.app-layout {
    --footer-height: 56px;
}

.footer-tabs .q-tabs,
.footer-tabs .q-tab {
    min-height: var(--footer-height);
}

/* The right detail drawer's q-page-container inherits the layout's drawer
   space as inline padding (e.g. padding-left equal to the fixed left nav
   drawer on desktop), which would leave a white gap on the drawer's left.
   The drawer handles its own positioning, so clear that inherited padding. */
:deep(.q-drawer--right .q-page-container) {
    padding: 0 !important;
}

/* Same source: the right drawer's q-page-sticky header gets inline
   `left: <nav drawer width>` from the layout's left drawer offset, leaving
   a white gap on its left. The drawer handles its own positioning, so the
   sticky header must start at the drawer's left edge. */
:deep(.q-drawer--right .q-page-sticky) {
    left: 0 !important;
}
</style>
