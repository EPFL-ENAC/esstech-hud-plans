<template>
    <q-page
        class="bg-white text-dark q-px-md q-pb-xl"
        style="padding-top: 64px"
        :aria-busy="isLoading || isSaving"
    >
        <page-header :title="`${buildingName} - Building Data`" />

        <q-banner v-if="state.error" class="bg-red-1 text-negative q-mb-md" role="alert">
            {{ loadErrorMessage }}
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading || isSaving" @click="refetch()" />
            </template>
        </q-banner>

        <div v-if="!draft && !state.error" role="status" aria-label="Loading building">
            <q-skeleton type="text" width="60%" class="q-mb-md" />
            <q-skeleton height="56px" class="q-mb-md" />
            <q-skeleton height="200px" square />
        </div>

        <q-form v-else-if="draft && !notFound" class="q-mb-lg" @submit="save">
            <h2 class="text-subtitle1 text-weight-bold q-mb-md">Localization</h2>
            <div v-if="isLoading" class="text-grey-7 q-mb-sm" role="status">
                <q-spinner color="primary" class="q-mr-sm" />
                Refreshing building…
            </div>
            <building-details-editor v-model="draft" :disable="isSaving" />
            <q-btn
                type="submit"
                label="Save"
                color="primary"
                class="full-width q-mt-md"
                unelevated
                no-caps
                :loading="isSaving"
                :disable="!canSave"
            />
            <q-banner v-if="saveErrorMessage" class="bg-red-1 text-negative q-mt-md" role="alert">
                {{ saveErrorMessage }}
            </q-banner>
        </q-form>

        <section class="q-mb-lg" aria-disabled="true">
            <h2 class="text-subtitle1 text-weight-bold q-mb-md">Classification</h2>
            <q-select
                v-model="buildingType"
                outlined
                :options="buildingTypeOptions"
                label="Building Type"
                class="q-mb-md"
                disable
            />

            <div class="row wrap q-gutter-sm q-mb-md">
                <q-chip
                    v-for="material in materials"
                    :key="material"
                    square
                    outline
                    color="primary"
                    class="bg-secondary"
                    disable
                >
                    <q-avatar
                        size="20px"
                        style="
                            border-radius: 4px;
                            border: 1px solid #e5e5ea;
                            background-size: cover;
                        "
                        :style="{
                            backgroundImage: `url(${swatchUrl(material)})`,
                        }"
                    />
                    {{ material }}
                </q-chip>
            </div>

            <q-select
                v-model="intendedUse"
                outlined
                :options="intendedUseOptions"
                label="Intended Use"
                class="q-mb-md"
                disable
            />
        </section>

        <q-btn
            label="Generate building recommendations"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            disable
        />
    </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { useRoute } from 'vue-router';
import BuildingDetailsEditor from 'src/components/BuildingDetailsEditor.vue';
import PageHeader from 'src/components/PageHeader.vue';
import {
    ApiError,
    isValidBuildingCreate,
    type Building,
    type BuildingCreate,
} from 'src/lib/buildings';
import { useBuildingQuery } from 'src/queries/buildings';
import { useUpdateBuildingMutation } from 'src/mutations/buildings';

const $q = useQuasar();
const route = useRoute();
const buildingId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''));
const { data: building, state, asyncStatus, refetch } = useBuildingQuery(buildingId);
const {
    mutateAsync,
    reset,
    isLoading: isSaving,
    errorMessage: saveErrorMessage,
} = useUpdateBuildingMutation();
const draft = ref<BuildingCreate | null>(null);
const baseline = ref<BuildingCreate | null>(null);
const isLoading = computed(() => asyncStatus.value === 'loading');
const buildingName = computed(() =>
    building.value?.id === buildingId.value
        ? building.value.name.trim() || 'Untitled building'
        : 'Building',
);
const notFound = computed(
    () => state.value.error instanceof ApiError && state.value.error.status === 404,
);
const loadErrorMessage = computed(() =>
    notFound.value
        ? 'Building not found.'
        : draft.value
          ? 'Could not refresh this building.'
          : 'Could not load this building.',
);
const isDirty = computed(
    () =>
        draft.value !== null &&
        baseline.value !== null &&
        (['name', 'address', 'latitude', 'longitude'] as const).some(
            (field) => draft.value![field] !== baseline.value![field],
        ),
);
const canSave = computed(
    () =>
        draft.value !== null &&
        isDirty.value &&
        isValidBuildingCreate(draft.value) &&
        !isSaving.value &&
        !notFound.value,
);

function setSavedDetails(building: Building) {
    const details: BuildingCreate = {
        name: building.name,
        address: building.address ?? null,
        latitude: building.latitude,
        longitude: building.longitude,
    };
    baseline.value = details;
    draft.value = { ...details };
}

// A late save may update its building's cache, but never another route's draft.
let routeGeneration = 0;
watch(
    buildingId,
    () => {
        routeGeneration++;
        draft.value = null;
        baseline.value = null;
        reset();
    },
    { immediate: true, flush: 'sync' },
);
watch(
    [buildingId, building],
    ([id, value]) => {
        if (value?.id === id && !isDirty.value && !isSaving.value) setSavedDetails(value);
    },
    { immediate: true, flush: 'sync' },
);
onBeforeUnmount(() => routeGeneration++);

async function save() {
    if (!canSave.value || !draft.value) return;
    const generation = routeGeneration;
    const variables = { buildingId: buildingId.value, details: { ...draft.value } };
    reset();
    try {
        const saved = await mutateAsync(variables);
        if (generation !== routeGeneration) return;
        setSavedDetails(saved);
        $q.notify({ type: 'positive', message: 'Building details saved.' });
    } catch {
        // Mutation state displays the error; keep the draft available for retry.
    }
}

const buildingType = ref('');
const intendedUse = ref('');
const materials = ref(['Brick_1', 'Concrete_1']);

const buildingTypeOptions = ['Residential', 'Commercial', 'Industrial', 'Public'];
const intendedUseOptions = ['Office', 'Housing', 'Storage', 'Mixed'];

function swatchUrl(material: string) {
    // Procedural swatch for the prototype; replace with real texture URLs in production.
    const colors: Record<string, string> = {
        Brick_1: 'c97b63',
        Concrete_1: 'b8b8b8',
        Wood_1: 'd4a373',
    };
    const color = colors[material] ?? '999999';
    return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'%3E%3Crect width='20' height='20' fill='%23${color}'/%3E%3C/svg%3E`;
}
</script>
