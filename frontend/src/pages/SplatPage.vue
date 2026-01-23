<script setup lang="ts">
import { useRoute } from "vue-router";
import { computed } from "vue";
import { useReactiveGenerator } from "unwrapped/vue";
import { AsyncResult, delay } from "unwrapped/core";
import SplatRenderer from "../components/SplatRenderer.vue";

const route = useRoute();
const generationId = computed(() => route.params.id as string);


const splat = useReactiveGenerator(generationId, function* () {
    while (true) {
        const fetched = yield* AsyncResult.fromValuePromise(
            fetch(`http://localhost:8000/splats/get/${generationId.value}`)
        );
        if (fetched.ok) {
            return yield* AsyncResult.fromValuePromise(fetched.arrayBuffer());
        }

        console.log("Splat not ready yet, polling again...");
        // Wait for some time before polling again
        yield* delay(5000);
    }
});

</script>

<template>
    <q-page class="row items-center justify-evenly">
        <div v-if="splat.isSuccess()">
            <splat-renderer :splat-data="splat.unwrapOrNull()!" />
        </div>
        <div v-else-if="splat.isLoading()">
            <p>Loading splat...</p>
        </div>
    </q-page>
</template>

<style scoped>
.upload-container {
    max-width: 400px;
    margin: 20px auto;
    padding: 20px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-family: sans-serif;
}

.success {
    color: #2e7d32;
    margin-top: 10px;
}

.error {
    color: #d32f2f;
    margin-top: 10px;
}

.info {
    color: #1976d2;
    margin-top: 10px;
}

button {
    margin-left: 10px;
    cursor: pointer;
}
</style>