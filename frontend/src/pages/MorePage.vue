<template>
    <q-page class="od-page od-page--scroll">
        <h1 class="od-page-title">More</h1>

        <div class="od-list">
            <div class="od-list-row" tabindex="0">
                <div class="od-list-row__content">
                    <div class="od-list-row__title">Account</div>
                </div>
                <q-icon name="chevron_right" class="od-list-row__chevron" />
            </div>
            <div class="od-list-row" tabindex="0">
                <div class="od-list-row__content">
                    <div class="od-list-row__title">Settings</div>
                </div>
                <q-icon name="chevron_right" class="od-list-row__chevron" />
            </div>
            <div class="od-list-row" tabindex="0">
                <div class="od-list-row__content">
                    <div class="od-list-row__title">Help & Support</div>
                </div>
                <q-icon name="chevron_right" class="od-list-row__chevron" />
            </div>
            <div class="od-list-row" tabindex="0" @click="handleLogout">
                <div class="od-list-row__content">
                    <div class="od-list-row__title od-text-negative">Log out</div>
                </div>
                <q-icon name="logout" class="od-list-row__chevron od-text-negative" />
            </div>
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { logout } from 'src/lib/auth';

const router = useRouter();

function handleLogout() {
    logout();
    void router.push('/login');
}
</script>
