<template>
    <div class="q-gutter-y-md">
        <q-input v-model="name" outlined :label="t('buildings.fields.name')" :disable="disable" />
        <q-input
            v-model="address"
            outlined
            :label="t('buildings.fields.address')"
            :disable="disable"
        />
        <div>
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
                    :label="t('buildings.fields.latitude')"
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
                    :label="t('buildings.fields.longitude')"
                    :disable="disable"
                />
            </div>
            <q-btn
                class="full-width q-mt-md"
                color="primary"
                outline
                icon="my_location"
                :label="t('buildings.fields.useCurrentLocation')"
                :loading="locating"
                :disable="disable"
                @click="useCurrentLocation"
            />
        </div>
        <p v-if="!isValidBuildingCreate(details)" class="text-negative q-mb-none" role="alert">
            {{ t('buildings.fields.invalidCoordinates') }}
        </p>
        <p v-else class="text-caption text-grey-7 q-mb-none">
            {{ t('buildings.fields.coordinatesHint') }}
        </p>
        <p v-if="locationError" class="text-negative q-mb-none" role="alert">{{ locationError }}</p>
        <building-location-map
            :latitude="details.latitude"
            :longitude="details.longitude"
            draggable
            @coords-change="onMapCoordsChange"
        />
    </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import BuildingLocationMap from 'src/components/BuildingLocationMap.vue';
import { type BuildingCreate, isValidBuildingCreate } from 'src/lib/buildings';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

withDefaults(defineProps<{ disable?: boolean }>(), { disable: false });
const details = defineModel<BuildingCreate>({ required: true });
const name = computed({
    get: () => details.value.name,
    set: (value: string | number | null) => {
        details.value = { ...details.value, name: String(value ?? '') };
    },
});
const address = computed({
    get: () => details.value.address ?? '',
    set: (value: string | number | null) => {
        const address = String(value ?? '');
        details.value = { ...details.value, address: address.trim() ? address : null };
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

function onMapCoordsChange(newLatitude: number, newLongitude: number) {
    details.value = {
        ...details.value,
        latitude: newLatitude,
        longitude: newLongitude,
    };
}

const locating = ref(false);
const locationError = ref<string | null>(null);

function useCurrentLocation() {
    if (!navigator.geolocation) {
        locationError.value = t('buildings.fields.geolocationUnavailable');
        return;
    }
    locating.value = true;
    locationError.value = null;
    navigator.geolocation.getCurrentPosition(
        (position) => {
            details.value = {
                ...details.value,
                latitude: Number(position.coords.latitude.toFixed(6)),
                longitude: Number(position.coords.longitude.toFixed(6)),
            };
            locating.value = false;
        },
        (error) => {
            locationError.value =
                error.code === error.PERMISSION_DENIED
                    ? t('buildings.fields.geolocationDenied')
                    : t('buildings.fields.geolocationFailed');
            locating.value = false;
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
}
</script>
