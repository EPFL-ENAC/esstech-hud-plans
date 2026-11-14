<template>
    <q-page
        class="bg-white text-dark q-pa-md q-pb-xl"
        style="padding-top: 64px"
        :aria-label="t('tasks.title')"
    >
        <page-header :title="t('tasks.title')" />

        <p class="text-grey-8">{{ t('tasks.memoryOnly') }}</p>

        <q-banner v-if="!queue.isOnline" class="bg-warning text-dark q-mb-md" role="status">
            <template #avatar>
                <q-icon name="wifi_off" />
            </template>
            {{ t('tasks.offline') }}
        </q-banner>

        <q-banner
            v-if="queue.authenticationRequired"
            class="bg-warning text-dark q-mb-md"
            role="status"
        >
            {{ t('tasks.authenticationRequired') }}
        </q-banner>

        <p v-if="hasWaitingTasks" class="text-grey-8">{{ t('tasks.waitingHelp') }}</p>
        <p v-if="queue.tasks.length === 0" role="status">{{ t('tasks.empty') }}</p>

        <q-list v-else bordered separator class="rounded-borders">
            <network-dependent-task-item
                v-for="task in queue.tasks"
                :key="task.id"
                :task="task"
                :retry-disabled="!queue.isOnline || queue.authenticationRequired"
                @retry="queue.retry"
                @cancel="queue.cancel"
            />
        </q-list>

        <p v-if="queue.tasks.length > 0" class="text-grey-8 q-mt-md">
            {{ t('tasks.cancelHint') }}
        </p>
    </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import PageHeader from 'src/components/PageHeader.vue';
import NetworkDependentTaskItem from 'src/components/NetworkDependentTaskItem.vue';
import { useNetworkDependentTasks } from 'src/stores/networkDependentTasks';

const { t } = useI18n();
const queue = useNetworkDependentTasks();
const hasWaitingTasks = computed(() => queue.tasks.some((task) => task.state.status === 'waiting'));
</script>
