<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <h1 class="od-h-page q-mb-lg">More</h1>

        <q-list class="q-gutter-y-md">
            <q-item class="od-card-row" tabindex="0">
                <q-item-section>
                    <div class="od-title">Account</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="chevron_right" size="20px" color="dark" />
                </q-item-section>
            </q-item>

            <q-item class="od-card-row" tabindex="0">
                <q-item-section>
                    <div class="od-title">Settings</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="chevron_right" size="20px" color="dark" />
                </q-item-section>
            </q-item>

            <q-item class="od-card-row" tabindex="0">
                <q-item-section>
                    <div class="od-title">Help &amp; Support</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="chevron_right" size="20px" color="dark" />
                </q-item-section>
            </q-item>

            <q-item class="od-card-row text-negative" clickable tabindex="0" @click="handleLogout">
                <q-item-section>
                    <div class="od-title">Log out</div>
                </q-item-section>
                <q-item-section side>
                    <q-icon name="logout" size="20px" />
                </q-item-section>
            </q-item>
        </q-list>
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
