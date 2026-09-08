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
                    ? t('buildings.picker.loadingSelected')
                    : t('buildings.picker.unavailable')
            "
            :label="t('buildings.title')"
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
            {{ t('buildings.list.loadFailed') }}
            <template #action>
                <q-btn
                    flat
                    :label="t('common.retry')"
                    :disable="isLoading || disable"
                    @click="refetch()"
                />
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
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

interface SelectOption {
    label: string;
    value: string | null;
}

withDefaults(defineProps<{ disable?: boolean }>(), { disable: false });
const selection = defineModel<BuildingSelection>({ required: true });
const emit = defineEmits<{ valid: [value: boolean] }>();
const { data: buildings, state, asyncStatus, refetch } = useAllBuildingsQuery();
const isLoading = computed(() => asyncStatus.value === 'loading');
const options = computed<SelectOption[]>(() => [
    { label: t('buildings.picker.createNew'), value: null },
    ...(buildings.value ?? []).map((building) => ({
        label: building.name.trim() || t('buildings.untitled'),
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
            label: t('buildings.picker.select'),
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
