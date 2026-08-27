<template>
    <svg
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        class="floor-plan-thumb"
        aria-hidden="true"
    >
        <!-- Outer footprint -->
        <rect
            x="13"
            y="13"
            width="38"
            height="38"
            rx="2"
            stroke="currentColor"
            stroke-width="3"
            stroke-linejoin="round"
        />
        <!-- Vertical divider wall (right room vs left rooms), door gap near the bottom -->
        <line x1="32" y1="13" x2="32" y2="40" stroke="currentColor" stroke-width="3" />
        <line x1="32" y1="46" x2="32" y2="51" stroke="currentColor" stroke-width="3" />
        <!-- Horizontal wall splitting the left rooms, door gap on the left side -->
        <line x1="20" y1="33" x2="32" y2="33" stroke="currentColor" stroke-width="3" />
    </svg>
</template>

<style scoped>
.floor-plan-thumb {
    width: 44px;
    height: 44px;
    color: currentColor;
}
</style>
