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
        </q-list>
    </q-page>
</template>

<script setup lang="ts">
import PageHeader from 'src/components/PageHeader.vue';
import PwaInstallButton from 'src/components/PwaInstallButton.vue';
import { useRouter } from 'vue-router';
import QueryStateSwitcher from 'src/components/QueryStateSwitcher.vue';
import { logout } from 'src/lib/auth';
import { useCurrentUserQuery } from 'src/queries/user';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const router = useRouter();
const { state, asyncStatus, refetch } = useCurrentUserQuery();

function displayValue(value: string | null): string {
    return value?.trim() || t('more.notProvided');
}

function handleLogout() {
    logout();
    void router.push('/login');
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
