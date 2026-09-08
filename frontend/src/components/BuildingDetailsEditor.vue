<template>
    <div class="q-gutter-y-md">
        <q-input v-model="name" outlined label="Building name (optional)" :disable="disable" />
        <div class="row q-col-gutter-md">
            <q-input
                v-model="latitude"
                class="col-12 col-sm-6"
                outlined
                clearable
                type="number"
                min="-90"
                max="90"
                step="any"
                label="Latitude (optional)"
                :disable="disable"
            />
            <q-input
                v-model="longitude"
                class="col-12 col-sm-6"
                outlined
                clearable
                type="number"
                min="-180"
                max="180"
                step="any"
                label="Longitude (optional)"
                :disable="disable"
            />
        </div>
        <p v-if="!isValidBuildingCreate(details)" class="text-negative q-mb-none" role="alert">
            Provide both coordinates or leave both empty. Latitude must be between −90 and 90, and
            longitude between −180 and 180.
        </p>
        <p v-else class="text-caption text-grey-7 q-mb-none">
            Provide both coordinates or leave both empty.
        </p>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { type BuildingCreate, isValidBuildingCreate } from 'src/lib/buildings';

withDefaults(defineProps<{ disable?: boolean }>(), { disable: false });
const details = defineModel<BuildingCreate>({ required: true });
const name = computed({
    get: () => details.value.name,
    set: (value: string | number | null) => {
        details.value = { ...details.value, name: String(value ?? '') };
    },
});

function coordinateModel(field: 'latitude' | 'longitude') {
    return computed({
        get: () => details.value[field],
        set: (value: string | number | null) => {
            details.value = {
                ...details.value,
                [field]: value === '' || value === null ? null : Number(value),
            };
        },
    });
}

const latitude = coordinateModel('latitude');
const longitude = coordinateModel('longitude');
</script>
