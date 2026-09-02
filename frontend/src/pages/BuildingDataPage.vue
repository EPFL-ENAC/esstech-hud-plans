<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header title="My Building - Building Data" />

        <section class="q-mb-lg">
            <h2 class="text-subtitle1 text-weight-bold q-mb-md">Localization</h2>
            <q-input v-model="address" outlined label="Address" class="q-mb-md" />
            <q-input v-model="coordinates" outlined label="GPS Coordinates">
                <template #append>
                    <q-btn flat dense icon="location_on" color="primary" />
                </template>
            </q-input>
        </section>

        <section class="q-mb-lg">
            <h2 class="text-subtitle1 text-weight-bold q-mb-md">Classification</h2>
            <q-select
                v-model="buildingType"
                outlined
                :options="buildingTypeOptions"
                label="Building Type"
                class="q-mb-md"
            />

            <div class="row wrap q-gutter-sm q-mb-md">
                <q-chip
                    v-for="material in materials"
                    :key="material"
                    square
                    outline
                    color="primary"
                    class="bg-secondary"
                    removable
                    @remove="removeMaterial(material)"
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
            />
        </section>

        <q-btn
            label="Generate building recommendations"
            color="primary"
            class="full-width"
            unelevated
            no-caps
            @click="generate"
        />
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useQuasar } from 'quasar';
import PageHeader from 'src/components/PageHeader.vue';

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
