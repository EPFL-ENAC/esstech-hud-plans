<template>
    <q-list separator class="building-list">
        <slot />
    </q-list>
</template>

<script setup lang="ts"></script>

<style scoped>
/* Add outer top/bottom borders only. Internal borders between items are
 * drawn by q-list--separator (border-top of subsequent items), so adding a
 * top border to the first item and a bottom border to the last item
 * produces no double borders. */
.building-list > :first-child {
    border-top: 1px solid rgba(0, 0, 0, 0.12);
}

.building-list > :last-child {
    border-bottom: 1px solid rgba(0, 0, 0, 0.12);
}
</style>
