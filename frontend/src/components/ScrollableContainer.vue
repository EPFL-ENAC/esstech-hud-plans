<script setup lang="ts">
import { ref, onUnmounted, useTemplateRef, onMounted } from 'vue';

interface Props {
    delay?: number;
    threshold?: number;
    containerClass?: string | Record<string, boolean> | Array<string | Record<string, boolean>>;
}

const props = withDefaults(defineProps<Props>(), {
    delay: 250,
    threshold: 50,
    containerClass: '',
});

const containerRef = useTemplateRef<HTMLDivElement>('container');
const isAtBottom = ref(true);
const showScrollBtn = ref(false);
let scrollBtnTimeout: ReturnType<typeof setTimeout> | null = null;

function handleScroll() {
    const el = containerRef.value;
    if (!el) return;

    const atBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + props.threshold;
    isAtBottom.value = atBottom;

    if (atBottom) {
        showScrollBtn.value = false;
        if (scrollBtnTimeout) {
            clearTimeout(scrollBtnTimeout);
            scrollBtnTimeout = null;
        }
    } else if (!scrollBtnTimeout && !showScrollBtn.value) {
        scrollBtnTimeout = setTimeout(() => {
            if (!isAtBottom.value) {
                showScrollBtn.value = true;
            }
            scrollBtnTimeout = null;
        }, props.delay);
    }
}

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
    const el = containerRef.value;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
}

function isScrolledToBottom(): boolean {
    return isAtBottom.value;
}

onMounted(() => {
    handleScroll(); // Check initial position
});

onUnmounted(() => {
    if (scrollBtnTimeout) clearTimeout(scrollBtnTimeout);
});

defineExpose({
    scrollToBottom,
    isScrolledToBottom,
});
</script>

<template>
    <div class="relative-position">
        <div ref="container" :class="['scroll-area', props.containerClass]" @scroll="handleScroll">
            <slot />
        </div>

        <transition enter-active-class="animated fadeIn" leave-active-class="animated fadeOut">
            <q-btn
                v-if="showScrollBtn"
                fab-mini
                icon="arrow_downward"
                color="primary"
                class="scroll-bottom-btn"
                @click="() => scrollToBottom()"
            >
                <q-tooltip>Scroll to bottom</q-tooltip>
            </q-btn>
        </transition>
    </div>
</template>

<style scoped>
.scroll-area {
    height: 100%;
    width: 100%;
    overflow-y: auto;
}

.scroll-bottom-btn {
    position: absolute;
    bottom: 12px;
    right: 16px;
    z-index: 10;
    pointer-events: none;
    opacity: 0;

    animation: scroll-bottom-btn-appear 0.3s ease-out forwards;
}

@keyframes scroll-bottom-btn-appear {
    0% {
        opacity: 0;
        transform: translateY(10px);
    }

    100% {
        opacity: 0.8;
        transform: translateY(0);
        pointer-events: all;
    }
}

.scroll-bottom-btn:hover {
    opacity: 1;
}
</style>
