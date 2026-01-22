<script setup lang="ts">
import * as THREE from "three";
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SplatMesh } from "@sparkjsdev/spark";
import { onMounted, useTemplateRef } from "vue";

const props = defineProps<{
    splatData: ArrayBuffer;
}>();

const container = useTemplateRef<HTMLDivElement>("container");

onMounted(() => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer();
    renderer.setSize(window.innerWidth, window.innerHeight);
    container.value?.appendChild(renderer.domElement);

    const butterfly = new SplatMesh({ fileBytes: props.splatData });
    butterfly.quaternion.set(1, 0, 0, 0);
    butterfly.position.set(0, 0, -3);
    scene.add(butterfly);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.minDistance = 0.3;
    controls.maxDistance = 20;
    controls.update();

    renderer.setAnimationLoop(function animate() {
        renderer.render(scene, camera);
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