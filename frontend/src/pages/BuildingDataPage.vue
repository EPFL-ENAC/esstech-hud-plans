<template>
    <q-page class="od-page od-page--scroll bg-white text-dark">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                color="primary"
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">My Building - Building Data</div>
        </div>

        <section class="q-mb-lg">
            <h2 class="od-h-form q-mb-md">Localization</h2>
            <q-input v-model="address" outlined label="Address" class="od-field q-mb-md" />
            <q-input v-model="coordinates" outlined label="GPS Coordinates" class="od-field">
                <template #append>
                    <q-btn flat dense icon="location_on" color="primary" />
                </template>
            </q-input>
        </section>

        <section class="q-mb-lg">
            <h2 class="od-h-form q-mb-md">Classification</h2>
            <q-select
                v-model="buildingType"
                outlined
                :options="buildingTypeOptions"
                label="Building Type"
                class="od-field q-mb-md"
            />

            <div class="od-material-chips q-mb-md">
                <div v-for="material in materials" :key="material" class="od-material-chip">
                    <div
                        class="od-material-chip__swatch"
                        :style="{
                            backgroundImage: `url(${swatchUrl(material)})`,
                            backgroundSize: 'cover',
                        }"
                    />
                    <span>{{ material }}</span>
                    <q-icon
                        name="close"
                        class="od-material-chip__remove"
                        @click="removeMaterial(material)"
                    />
                </div>
            </div>

            <q-select
                v-model="intendedUse"
                outlined
                :options="intendedUseOptions"
                label="Intended Use"
                class="od-field q-mb-md"
            />
        </section>

        <q-btn
            label="Generate building recommendations"
            color="primary"
            class="od-btn full-width"
            unelevated
            no-caps
            @click="generate"
        />
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useQuasar } from 'quasar';

const $q = useQuasar();

const address = ref('');
const coordinates = ref('');
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

function removeMaterial(material: string) {
    materials.value = materials.value.filter((m) => m !== material);
}

function generate() {
    $q.notify({
        type: 'positive',
        message: 'Building recommendations generated.',
        position: 'top',
    });
}
</script>
