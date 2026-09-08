<template>
    <q-page class="bg-white text-dark q-px-md q-pb-xl" style="padding-top: 64px">
        <page-header title="New Capture" />

        <q-card flat bordered square class="bg-grey-3 flex flex-center text-grey-7 q-mb-md">
            <div class="column items-center q-py-xl q-gutter-sm">
                <q-icon name="movie" size="48px" />
                <span>Video Preview</span>
            </div>
        </q-card>
        <div class="text-primary q-mb-md">2:34 &nbsp; 253mb</div>

        <q-input v-model="name" outlined label="Building 1" class="q-mb-md" />

        <q-input
            v-model="description"
            type="textarea"
            outlined
            label="Description"
            class="q-mb-md"
        />

        <q-select
            v-model="environment"
            outlined
            :options="environmentOptions"
            label="Environment"
            class="q-mb-xl"
        />

        <q-btn
            label="Start Processing (10-60min)"
            color="primary"
            class="full-width"
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
import PageHeader from 'src/components/PageHeader.vue';

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
