<script setup lang="ts">
/** Inline fit score bar for tables. */
defineProps<{ value: number }>()
</script>

<template>
  <div class="flex items-center gap-2.5">
    <span class="w-7 text-right text-sm font-semibold tabular">{{ Math.round(value) }}</span>
    <div class="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden="true">
      <div class="h-full rounded-full bg-series-1" :style="{ width: `${value}%` }"></div>
    </div>
  </div>
</template>
