<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div
    data-slot="skeleton"
    aria-hidden="true"
    :class="
      cn(
        'animate-shimmer rounded-md bg-[linear-gradient(90deg,var(--muted)_0%,color-mix(in_oklch,var(--muted)_55%,var(--card))_50%,var(--muted)_100%)] bg-[length:200%_100%]',
        props.class,
      )
    "
  ></div>
</template>
