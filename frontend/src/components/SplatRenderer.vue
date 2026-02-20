<script setup lang="ts">
import * as THREE from 'three';
import { SplatMesh, SparkControls } from '@sparkjsdev/spark';
import { onMounted, useTemplateRef } from 'vue';

const props = defineProps<{
    splatData: ArrayBuffer;
}>();

const container = useTemplateRef<HTMLDivElement>('container');

onMounted(() => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
        60,
        window.innerWidth / window.innerHeight,
        0.1,
        1000,
    );
    const renderer = new THREE.WebGLRenderer();
    renderer.setSize(window.innerWidth, window.innerHeight);
    container.value?.appendChild(renderer.domElement);

    // Clone the ArrayBuffer to prevent detachment issues with Web Workers
    const clonedBuffer = props.splatData.slice(0);
    const mesh = new SplatMesh({ fileBytes: clonedBuffer });
    mesh.quaternion.set(1, 0, 0, 0);
    mesh.position.set(0, 0, -3);
    scene.add(mesh);

    const controls = new SparkControls({
        canvas: renderer.domElement,
    });

    renderer.setAnimationLoop(function animate() {
        renderer.render(scene, camera);
        controls.update(camera);
    });
});
</script>

<template>
    <div ref="container" class="three-container"></div>
</template>

<style scoped>
.three-container {
    min-width: 0;
    max-width: 100%;
    height: 100%;
    display: block;
    margin: 0;
    padding: 0;
    overflow: hidden;
}
</style>
