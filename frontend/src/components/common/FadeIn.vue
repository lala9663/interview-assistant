<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

/** Subtle mount transition (opacity + 6px rise). Reduced motion is honoured globally in index.css. */
const props = withDefaults(defineProps<{ delay?: number; class?: HTMLAttributes['class'] }>(), { delay: 0 })
</script>

<template>
  <div
    :class="['animate-in fade-in-0 slide-in-from-bottom-1.5', props.class]"
    :style="{
      animationDuration: '280ms',
      animationDelay: `${delay}s`,
      animationTimingFunction: 'cubic-bezier(0.22, 1, 0.36, 1)',
      animationFillMode: 'both',
    }"
  >
    <slot />
  </div>
</template>
