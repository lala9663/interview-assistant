<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Candidate pseudonym (CAND-0007). Real names are never shown. */
const props = withDefaults(defineProps<{ value: string; size?: 'sm' | 'md' | 'lg'; class?: HTMLAttributes['class'] }>(), { size: 'md' })
</script>

<template>
  <span
    :class="
      cn(
        'inline-flex items-center font-mono font-semibold tracking-tight whitespace-nowrap tabular',
        size === 'sm' && 'text-[13px]',
        size === 'md' && 'text-sm',
        size === 'lg' && 'text-xl',
        props.class,
      )
    "
    >{{ value }}</span
  >
</template>
