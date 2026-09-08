<script setup lang="ts">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SplatMesh, SparkRenderer } from '@sparkjsdev/spark';
import { onMounted, useTemplateRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';

const { t } = useI18n();

const props = defineProps<{
    splatData: ArrayBuffer;
}>();
const emit = defineEmits<{
    ready: [];
    error: [error: unknown];
}>();

const container = useTemplateRef<HTMLDivElement>('container');

onMounted(() => {
    watch(
        () => props.splatData,
        (data, _, onCleanup) => {
            const host = container.value;
            if (!host) return;

            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(60, 1, 0.01, 1000);
            let renderer: THREE.WebGLRenderer | null = null;
            let controls: OrbitControls | null = null;
            let mesh: SplatMesh | null = null;
            let spark: SparkRenderer | null = null;
            let observer: ResizeObserver | null = null;
            let disposed = false;
            let frameInProgress = false;
            let needsSort = true;
            let ready = false;

            function dispose(): void {
                if (disposed) return;
                disposed = true;
                observer?.disconnect();
                renderer?.setAnimationLoop(null);
                controls?.dispose();
                renderer?.domElement.remove();
                // Keep the GPU alive until the current sort/readback has finished.
                if (!frameInProgress) releaseResources();
            }

            function releaseResources(): void {
                if (mesh?.isInitialized) mesh.dispose();
                spark?.defaultView.dispose();
                spark?.geometry.dispose();
                spark?.material.dispose();
                scene.clear();
                renderer?.dispose();
                renderer?.forceContextLoss();
            }
            onCleanup(dispose);

            async function initialize(): Promise<void> {
                try {
                    // Spark's worker may transfer ownership of the input buffer.
                    mesh = new SplatMesh({ fileBytes: data.slice(0) });
                    await mesh.initialized;
                    if (disposed) {
                        mesh.dispose();
                        return;
                    }
                    mesh.quaternion.set(1, 0, 0, 0);
                    mesh.updateMatrixWorld(true);
                    const bounds = mesh.getBoundingBox().applyMatrix4(mesh.matrixWorld);
                    if (bounds.isEmpty()) throw new Error('The splat contains no points');
                    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
                    if (!Number.isFinite(sphere.radius)) throw new Error('Invalid splat bounds');

                    renderer = new THREE.WebGLRenderer();
                    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
                    renderer.setClearColor(0x181818);
                    renderer.domElement.setAttribute('aria-label', t('plans.splat.viewer'));
                    renderer.domElement.setAttribute('role', 'img');
                    host!.appendChild(renderer.domElement);
                    spark = new SparkRenderer({ renderer, autoUpdate: false });
                    spark.defaultView.setAutoUpdate(false);
                    scene.add(spark, mesh);
                    controls = new OrbitControls(camera, renderer.domElement);
                    controls.enableDamping = true;
                    controls.target.copy(sphere.center);

                    const resize = (): void => {
                        if (!renderer || !host) return;
                        const width = Math.max(host.clientWidth, 1);
                        const height = Math.max(host.clientHeight, 1);
                        renderer.setSize(width, height, false);
                        camera.aspect = width / height;
                        camera.updateProjectionMatrix();
                        needsSort = true;
                    };
                    resize();
                    const radius = Math.max(sphere.radius, 0.01);
                    const verticalFov = THREE.MathUtils.degToRad(camera.fov);
                    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
                    const distance =
                        (radius / Math.sin(Math.min(verticalFov, horizontalFov) / 2)) * 1.2;
                    camera.position.copy(sphere.center).add(new THREE.Vector3(0, 0, distance));
                    camera.near = Math.max(radius / 1000, 0.001);
                    camera.far = Math.max(distance + radius * 100, 100);
                    camera.updateProjectionMatrix();
                    controls.update();
                    observer = new ResizeObserver(resize);
                    observer.observe(host!);

                    async function renderFrame(): Promise<void> {
                        if (disposed || frameInProgress) return;
                        frameInProgress = true;
                        try {
                            const moved = controls?.update();
                            if (needsSort || moved) {
                                needsSort = false;
                                await spark?.defaultView.prepare({ scene, camera });
                            }
                            if (disposed) return;
                            renderer?.render(scene, camera);
                            if (!ready) {
                                ready = true;
                                emit('ready');
                            }
                        } catch (error) {
                            if (disposed) return;
                            dispose();
                            emit('error', error);
                        } finally {
                            frameInProgress = false;
                            if (disposed) releaseResources();
                        }
                    }
                    renderer.setAnimationLoop(() => void renderFrame());
                } catch (error) {
                    if (disposed) return;
                    dispose();
                    emit('error', error);
                }
            }
            void initialize();
        },
        { immediate: true },
    );
});
</script>

<template>
    <div ref="container" class="three-container"></div>
</template>

<style scoped>
.three-container {
    min-width: 0;
    max-width: 100%;
    width: 100%;
    height: clamp(260px, 50vh, 520px);
    border-radius: 4px;
    background: #181818;
    display: block;
    margin: 0;
    padding: 0;
    overflow: hidden;
}

.three-container :deep(canvas) {
    display: block;
    width: 100%;
    height: 100%;
}
</style>
