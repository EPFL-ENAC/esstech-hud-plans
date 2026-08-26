<template>
    <q-page class="od-page od-page--scroll">
        <div class="od-topbar">
            <q-btn
                flat
                dense
                icon="arrow_back"
                label="Back"
                no-caps
                class="od-topbar__back"
                @click="$router.back()"
            />
            <div class="od-topbar__title">New Capture</div>
        </div>

        <div class="od-placeholder od-placeholder--video">Video Preview</div>
        <div class="od-text-primary q-mb-md">2:34 &nbsp; 253mb</div>

        <q-input v-model="name" outlined label="Building 1" class="od-input q-mb-md" />

        <q-input
            v-model="description"
            type="textarea"
            outlined
            label="Description"
            class="od-textarea q-mb-md"
            input-style="min-height: 80px;"
        />

        <q-select
            v-model="environment"
            outlined
            :options="environmentOptions"
            label="Environment"
            class="od-select q-mb-xl"
        />

        <q-btn
            label="Start Processing (10-60min)"
            color="primary"
            class="od-btn od-btn--primary full-width"
            unelevated
            no-caps
            @click="startProcessing"
        />
    </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useBuildingsStore } from 'src/stores/buildings';

const router = useRouter();
const $q = useQuasar();
const buildingsStore = useBuildingsStore();

const name = ref('Building 1');
const description = ref('');
const environment = ref('indoors');
const environmentOptions = ['indoors', 'outdoors'];
const duration = '2:34';
const size = '253mb';

function startProcessing() {
    const id = buildingsStore.startProcessing({
        name: name.value,
        description: description.value,
        environment: environment.value as 'indoors' | 'outdoors',
        duration,
        size,
    });

    $q.notify({
        type: 'positive',
        message: 'Capture uploaded and processing started.',
        position: 'top',
    });
    void router.push(`/capture/processing/${id}`);
}
</script>
