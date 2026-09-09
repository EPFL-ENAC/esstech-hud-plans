<template>
    <section aria-labelledby="reconstructions-title" :aria-busy="isLoading" class="q-mb-lg">
        <h2 id="reconstructions-title" class="text-h6 text-weight-bold q-mb-md">
            {{ t('reconstructions.title') }}
        </h2>
        <q-btn
            :label="t('reconstructions.new')"
            icon="add"
            color="primary"
            class="full-width q-mb-md"
            unelevated
            no-caps
            :to="{ path: '/capture/new', query: { buildingId } }"
        />

        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ data ? t('reconstructions.refreshFailed') : t('reconstructions.loadFailed') }}
            <template #action>
                <q-btn flat :label="t('common.retry')" :disable="isLoading" @click="refetch()" />
            </template>
        </q-banner>
        <div
            v-if="state.status === 'pending'"
            role="status"
            :aria-label="t('reconstructions.loading')"
        >
            <q-skeleton v-for="index in 3" :key="index" height="72px" class="q-mb-sm" />
        </div>
        <template v-else-if="data">
            <div v-if="isLoading" class="text-grey-7 q-mb-sm" role="status">
                <q-spinner color="primary" class="q-mr-sm" />
                {{ t('reconstructions.refreshing') }}
            </div>
            <q-list v-if="reconstructions.length" bordered separator class="rounded-borders">
                <q-expansion-item
                    v-for="reconstruction in reconstructions"
                    :key="reconstruction.id"
                    :model-value="expandedId === reconstruction.id"
                    expand-separator
                    @update:model-value="(open) => setExpanded(reconstruction.id, open)"
                >
                    <template #header>
                        <q-item-section>
                            <q-item-label class="text-subtitle1 text-weight-medium">
                                {{
                                    t('reconstructions.named', {
                                        id: reconstruction.id.slice(0, 8),
                                    })
                                }}
                            </q-item-label>
                            <q-item-label caption>
                                {{ dateFormatter.format(new Date(reconstruction.created_at)) }}
                            </q-item-label>
                            <q-item-label>
                                <reconstruction-status-chip
                                    :reconstruction="reconstruction"
                                    :tooltip="t('reconstructions.attempt')"
                                />
                            </q-item-label>
                        </q-item-section>
                    </template>
                    <div class="q-pa-md">
                        <reconstruction-video
                            :building-id="buildingId"
                            :reconstruction-id="reconstruction.id"
                            :active="expandedId === reconstruction.id"
                        />
                        <section
                            v-if="isProcessing(reconstruction)"
                            class="q-my-lg"
                            :aria-label="t('processing.details')"
                        >
                            <h3 class="text-h6 text-weight-bold q-mt-none q-mb-md">
                                {{ t('processing.details') }}
                            </h3>
                            <q-list class="q-gutter-y-md">
                                <q-item
                                    clickable
                                    :aria-label="t('processing.details')"
                                    :to="`/capture/processing/${buildingId}`"
                                >
                                    <q-item-section avatar>
                                        <q-avatar
                                            square
                                            size="48px"
                                            font-size="31px"
                                            color="white"
                                            text-color="primary"
                                            class="avatar-icon"
                                        >
                                            <q-icon name="tune" />
                                        </q-avatar>
                                    </q-item-section>
                                    <q-item-section>
                                        <q-item-label class="text-subtitle1 text-weight-medium">
                                            {{ t('processing.details') }}
                                        </q-item-label>
                                        <q-item-label caption>
                                            {{ t('processing.detailsDescription') }}
                                        </q-item-label>
                                    </q-item-section>
                                    <q-item-section side>
                                        <q-icon name="chevron_right" size="20px" color="dark" />
                                    </q-item-section>
                                </q-item>
                            </q-list>
                        </section>
                        <section
                            v-else-if="
                                reconstruction.status !== 'cancelled' &&
                                reconstruction.status !== 'failed'
                            "
                            class="q-my-lg"
                            :aria-label="t('plans.associated')"
                        >
                            <h3 class="text-h6 text-weight-bold q-mt-none q-mb-md">
                                {{ t('plans.associated') }}
                            </h3>
                            <q-list class="q-gutter-y-md">
                                <q-item
                                    clickable
                                    :aria-label="t('plans.twoDimensional')"
                                    :disable="!hasSplat(reconstruction)"
                                    :to="`/building/${buildingId}/plan/2d?reconstruction=${reconstruction.id}`"
                                >
                                    <q-item-section avatar>
                                        <q-avatar
                                            square
                                            size="48px"
                                            font-size="31px"
                                            color="white"
                                            text-color="primary"
                                            class="avatar-icon"
                                        >
                                            <q-icon name="crop_square" />
                                        </q-avatar>
                                    </q-item-section>
                                    <q-item-section>
                                        <q-item-label class="text-subtitle1 text-weight-medium">
                                            {{ t('plans.twoDimensional') }}
                                        </q-item-label>
                                        <q-item-label caption>
                                            {{ t('plans.twoDimensionalDescription') }}
                                        </q-item-label>
                                    </q-item-section>
                                    <q-item-section side>
                                        <q-icon name="chevron_right" size="20px" color="dark" />
                                    </q-item-section>
                                </q-item>
                                <q-item
                                    clickable
                                    :aria-label="t('plans.threeDimensional')"
                                    :disable="!hasSplat(reconstruction)"
                                    :to="{
                                        name: 'reconstruction-3d-plan',
                                        params: {
                                            buildingId,
                                            reconstructionId: reconstruction.id,
                                        },
                                    }"
                                >
                                    <q-item-section avatar>
                                        <q-avatar
                                            square
                                            size="48px"
                                            font-size="31px"
                                            color="white"
                                            text-color="primary"
                                            class="avatar-icon"
                                        >
                                            <q-icon name="view_in_ar" />
                                        </q-avatar>
                                    </q-item-section>
                                    <q-item-section>
                                        <q-item-label class="text-subtitle1 text-weight-medium">
                                            {{ t('plans.threeDimensional') }}
                                        </q-item-label>
                                        <q-item-label caption>
                                            {{ t('plans.threeDimensionalDescription') }}
                                        </q-item-label>
                                    </q-item-section>
                                    <q-item-section side>
                                        <q-icon name="chevron_right" size="20px" color="dark" />
                                    </q-item-section>
                                </q-item>
                                <q-tooltip v-if="!hasSplat(reconstruction)">
                                    {{ t('plans.unavailable') }}
                                </q-tooltip>
                            </q-list>
                        </section>
                        <div v-else class="q-my-lg" aria-hidden="true" />
                        <q-btn
                            :label="t('reconstructions.deleteCapture')"
                            outline
                            color="negative"
                            class="full-width"
                            unelevated
                            no-caps
                            disable
                        />
                    </div>
                </q-expansion-item>
            </q-list>
            <p v-else class="text-grey-7" role="status">
                {{ offset === 0 ? t('reconstructions.empty') : t('reconstructions.emptyPage') }}
            </p>
        </template>
        <nav
            v-if="data || offset > 0"
            :aria-label="t('reconstructions.pagination')"
            class="row justify-center q-pt-md"
        >
            <q-pagination
                v-model="page"
                :max="page + Number(hasNext)"
                :max-pages="5"
                :boundary-numbers="false"
                :ellipses="false"
                direction-links
                color="primary"
                :disable="isLoading"
            />
        </nav>
    </section>
</template>

<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue';
import ReconstructionStatusChip from 'src/components/ReconstructionStatusChip.vue';
import ReconstructionVideo from 'src/components/ReconstructionVideo.vue';
import type { Reconstruction } from 'src/lib/buildings';
import { RECONSTRUCTIONS_PAGE_SIZE, useReconstructionsQuery } from 'src/queries/reconstructions';
import { useI18n } from 'vue-i18n';

const { t, locale } = useI18n();

const props = defineProps<{ buildingId: string }>();
const offset = ref(0);
const expandedId = ref<string | null>(null);
const {
    data,
    state,
    refetch,
    isForegroundLoading: isLoading,
} = useReconstructionsQuery(toRef(props, 'buildingId'), offset);
const reconstructions = computed(() => data.value?.slice(0, RECONSTRUCTIONS_PAGE_SIZE) ?? []);
const hasNext = computed(() => (data.value?.length ?? 0) > RECONSTRUCTIONS_PAGE_SIZE);
const page = computed({
    get: () => offset.value / RECONSTRUCTIONS_PAGE_SIZE + 1,
    set: (value: number) => {
        expandedId.value = null;
        offset.value = (value - 1) * RECONSTRUCTIONS_PAGE_SIZE;
    },
});
const dateFormatter = computed(
    () =>
        new Intl.DateTimeFormat(locale.value, {
            dateStyle: 'medium',
            timeStyle: 'short',
        }),
);

function setExpanded(id: string, open: boolean) {
    if (open) expandedId.value = id;
    else if (expandedId.value === id) expandedId.value = null;
}
function hasSplat(reconstruction: Reconstruction): boolean {
    return reconstruction.status === 'completed' && reconstruction.splat_path !== null;
}
function isProcessing(reconstruction: Reconstruction): boolean {
    return ['preparing', 'scheduled', 'running'].includes(reconstruction.status);
}
watch(reconstructions, (rows) => {
    if (!rows.some(({ id }) => id === expandedId.value)) expandedId.value = null;
});
</script>
