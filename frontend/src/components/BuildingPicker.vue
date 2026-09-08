<template>
    <div class="q-gutter-y-md">
        <q-select
            v-model="selectedOption"
            outlined
            :options="options"
            :loading="isLoading"
            :disable="disable"
            :error="!hasResolvedBuilding"
            :error-message="
                isLoading
                    ? 'Loading the selected building…'
                    : 'Choose an available building or Create new.'
            "
            label="Building"
        >
            <template #option="scope">
                <q-item v-bind="scope.itemProps">
                    <q-item-section>
                        <q-item-label>{{ scope.opt.label }}</q-item-label>
                    </q-item-section>
                </q-item>
                <q-separator
                    v-if="scope.index === 0 && options.length > 1"
                    class="q-virtual-scroll--with-prev"
                />
            </template>
        </q-select>

        <q-banner v-if="state.error" class="bg-red-1 text-negative" role="alert">
            Could not load your buildings.
            <template #action>
                <q-btn flat label="Retry" :disable="isLoading || disable" @click="refetch()" />
            </template>
        </q-banner>

        <building-details-editor
            v-if="selection.buildingId === null"
            v-model="newBuilding"
            :disable="disable"
        />
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import BuildingDetailsEditor from 'src/components/BuildingDetailsEditor.vue';
import {
    type BuildingCreate,
    type BuildingSelection,
    isValidBuildingCreate,
} from 'src/lib/buildings';
import { useAllBuildingsQuery } from 'src/queries/buildings';

interface SelectOption {
    label: string;
    value: string | null;
}

withDefaults(defineProps<{ disable?: boolean }>(), { disable: false });
const selection = defineModel<BuildingSelection>({ required: true });
const emit = defineEmits<{ valid: [value: boolean] }>();
const { data: buildings, state, asyncStatus, refetch } = useAllBuildingsQuery();
const isLoading = computed(() => asyncStatus.value === 'loading');
const createNewOption: SelectOption = { label: 'Create new', value: null };
const options = computed<SelectOption[]>(() => [
    createNewOption,
    ...(buildings.value ?? []).map((building) => ({
        label: building.name.trim() || 'Untitled building',
        value: building.id,
    })),
]);

// Retain unsaved details when switching between a new and an existing building.
const draft = ref<BuildingCreate>({ name: '', latitude: null, longitude: null });
watch(
    selection,
    (value) => {
        if (value.buildingId === null) draft.value = value.building;
    },
    { immediate: true, flush: 'sync' },
);
const newBuilding = computed({
    get: () => (selection.value.buildingId === null ? selection.value.building : draft.value),
    set: (building: BuildingCreate) => {
        selection.value = { buildingId: null, building };
    },
});
const selectedOption = computed<SelectOption>({
    get: () =>
        options.value.find((option) => option.value === selection.value.buildingId) ?? {
            label: 'Select a building',
            value: selection.value.buildingId,
        },
    set: (option) => {
        selection.value =
            option.value === null
                ? { buildingId: null, building: draft.value }
                : { buildingId: option.value };
    },
});
const hasResolvedBuilding = computed(
    () =>
        selection.value.buildingId === null ||
        options.value.some((option) => option.value === selection.value.buildingId),
);
const isValid = computed(() =>
    selection.value.buildingId === null
        ? isValidBuildingCreate(selection.value.building)
        : hasResolvedBuilding.value,
);
watch(isValid, (value) => emit('valid', value), { immediate: true, flush: 'sync' });
</script>
