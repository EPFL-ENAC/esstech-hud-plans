<template>
    <q-page class="bg-white text-dark q-pa-md q-pb-xl" style="padding-top: 64px">
        <page-header :back="false" :title="t('navigation.more')" />

        <section class="account" aria-labelledby="account-heading">
            <h2 id="account-heading" class="account-heading">{{ t('more.account') }}</h2>

            <QueryStateSwitcher
                :state="state"
                :async-status="asyncStatus"
                :retry="refetch"
                :loading-message="t('more.accountLoading')"
                :error-message="t('more.accountLoadFailed')"
            >
                <template #pending>
                    <div class="account-identity" aria-hidden="true">
                        <span class="account-placeholder account-placeholder-icon" />
                        <div class="account-content">
                            <span class="account-placeholder account-placeholder-name" />
                            <div class="account-details">
                                <span class="account-placeholder" />
                                <span class="account-divider">|</span>
                                <span class="account-placeholder" />
                            </div>
                        </div>
                    </div>
                </template>
                <template #success="{ data: user }">
                    <div class="account-identity">
                        <q-icon name="person" size="64px" aria-hidden="true" />
                        <div class="account-content">
                            <p class="account-name">{{ displayValue(user.name) }}</p>
                            <div class="account-details">
                                <span>{{ displayValue(user.username) }}</span>
                                <span class="account-divider" aria-hidden="true">|</span>
                                <span>{{ displayValue(user.email) }}</span>
                            </div>
                        </div>
                    </div>
                </template>
            </QueryStateSwitcher>
        </section>

        <pwa-install-button class="q-mb-md" />
        <q-list class="more-links">
            <q-card flat bordered class="link-card">
                <q-item clickable v-ripple :to="{ name: 'uploads' }">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">
                            {{ t('uploads.title') }}
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" aria-hidden="true" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered class="link-card">
                <q-item clickable v-ripple :to="{ name: 'settings' }">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">
                            {{ t('more.settings') }}
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered class="link-card items-center">
                <q-item clickable v-ripple :to="{ name: 'help' }">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">
                            {{ t('more.help') }}
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered class="link-card items-center">
                <q-item clickable v-ripple :to="{ name: 'terms' }">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">
                            {{ t('terms.title') }}
                        </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="chevron_right" size="20px" color="dark" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered clickable class="link-card" @click="handleLogout">
                <q-item class="text-negative">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">{{
                            t('auth.logOut')
                        }}</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="logout" size="20px" />
                    </q-item-section>
                </q-item>
            </q-card>

            <q-card flat bordered clickable class="link-card" @click="handleDeleteAllData">
                <q-item class="text-negative">
                    <q-item-section>
                        <q-item-label class="text-subtitle1 text-weight-medium">{{
                            t('more.deleteAllData')
                        }}</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                        <q-icon name="delete_forever" size="20px" />
                    </q-item-section>
                </q-item>
            </q-card>
        </q-list>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import PwaInstallButton from 'src/components/PwaInstallButton.vue';
import { useRouter } from 'vue-router';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import { useCurrentUserQuery } from 'src/queries/user';
import { useI18n } from 'vue-i18n';
import { useQuasar } from 'quasar';
import { ref } from 'vue';
import { deleteAllData } from 'src/lib/buildings';
import { clearLocalData, logout } from 'src/lib/auth';

const { t } = useI18n();
const $q = useQuasar();
const deleting = ref(false);

const router = useRouter();
const { state, asyncStatus, refetch } = useCurrentUserQuery();

function displayValue(value: string | null): string {
    return value?.trim() || t('more.notProvided');
}

function handleLogout() {
    logout();
    void router.push('/login');
}

function handleDeleteAllData() {
    if (deleting.value) return;
    $q.dialog({
        title: t('more.deleteAllDataTitle'),
        message: t('more.deleteAllDataWarning', { keyword: t('more.deleteAllDataKeyword') }),
        prompt: {
            model: '',
            type: 'text',
            isValid: (value: string) =>
                value.trim().toUpperCase() === t('more.deleteAllDataKeyword'),
        },
        cancel: { label: t('common.cancel'), flat: true, noCaps: true },
        ok: { label: t('more.deleteAllDataConfirm'), color: 'negative', noCaps: true },
    }).onOk(() => {
        void confirmDeleteAllData();
    });
}

function confirmDeleteAllData() {
    deleting.value = true;
    deleteAllData()
        .then(clearLocalData)
        .then(() => {
            $q.dialog({
                title: t('more.deleteAllDataDoneTitle'),
                message: t('more.deleteAllDataDone'),
                ok: { label: t('common.close'), flat: true, noCaps: true },
                // Fires for OK, Cancel and ESC; data is gone, every path signs out.
            }).onDismiss(finishSignOut);
        })
        .catch(() => {
            $q.notify({ type: 'negative', message: t('more.deleteAllDataFailed') });
        })
        .finally(() => {
            deleting.value = false;
        });
}

function finishSignOut() {
    logout();
    // Full reload instead of router.push: clears in-memory query caches so a
    // re-login with the same identity cannot show data deleted on the server.
    // Hash-only navigation: a real path would change window.location.pathname,
    // which keycloakRedirectUri derives from.
    window.location.hash = '#/login';
    window.location.reload();
}
</script>

<style scoped>
.more-links {
    display: grid;
    gap: 1rem;
}

.account {
    display: grid;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 1rem;
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 4px;
}

.account-heading {
    margin: 0;
    font-size: 1rem;
    font-weight: 500;
    line-height: 1.5;
}

.account-identity {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.75rem;
    user-select: text;
    overflow-wrap: anywhere;
}

.account-content {
    display: grid;
    min-width: 0;
}

.account-name {
    margin: 0;
    font-size: 1rem;
    font-weight: 500;
    line-height: 1.5;
}

.account-details {
    display: flex;
    gap: 0.5rem;
    color: #616161;
    overflow-wrap: anywhere;
}

.account-placeholder {
    display: block;
    height: 1.25rem;
    border-radius: 4px;
    background: #eee;
}

.account-placeholder-icon {
    width: 24px;
    height: 24px;
    border-radius: 50%;
}

.account-placeholder-name {
    width: 60%;
    height: 1.5rem;
}

@media (max-width: 599px) {
    .account-details {
        flex-direction: column;
    }

    .account-divider {
        display: none;
    }
}
</style>
