<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Fit score 0-100 as a small ring. The ring fill is the accent; the number carries the value. */
const props = withDefaults(defineProps<{ value: number; size?: number; class?: HTMLAttributes['class'] }>(), { size: 44 })
const stroke = computed(() => (props.size >= 56 ? 5 : 4))
const r = computed(() => (props.size - stroke.value) / 2)
const c = computed(() => 2 * Math.PI * r.value)
</script>

<template>
  <div :class="cn('relative inline-flex shrink-0 items-center justify-center', props.class)" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size" :height="size" class="-rotate-90" aria-hidden="true">
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="var(--muted)" :stroke-width="stroke" />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="r"
        fill="none"
        stroke="var(--series-1)"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="c"
        :stroke-dashoffset="c * (1 - value / 100)"
        class="transition-[stroke-dashoffset] duration-700"
      />
    </svg>
    <span :class="cn('absolute font-semibold tabular', size >= 56 ? 'text-base' : 'text-[13px]')">{{ Math.round(value) }}</span>
    <span class="sr-only">적합도 {{ Math.round(value) }}점</span>
  </div>
</template>
