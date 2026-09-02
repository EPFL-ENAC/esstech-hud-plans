<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl">
        <h1 class="text-h5 text-weight-bold q-mb-lg">More</h1>

        <q-list class="q-gutter-y-md">
            <q-card flat bordered class="items-center">
                <q-item>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium"
                            >Account</q-item-label
                        >
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered class="items-center">
                <q-item>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium"
                            >Settings</q-item-label
                        >
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered class="items-center">
                <q-item>
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">
                            Help &amp; Support
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered clickable @click="handleLogout">
                <q-item class="text-negative">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium"
                            >Log out</q-item-label
                        >
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="logout" size="20px" />
                    </q-item-section>
                </q-item>
            </q-card>
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
