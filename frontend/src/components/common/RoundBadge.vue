<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import type { RoundRef } from '@/api/types'
import { cn } from '@/lib/utils'

/**
 * 차수 badge. Always the same neutral gray, everywhere: the round never carries a color (statuses
 * do, StepStatusChip). Short "2차", or with `full` the header form "2차 · 임원 면접"; `strong` is
 * the bold header variant. Pass `label` alone for 최종.
 */
const props = defineProps<{
  round?: Pick<RoundRef, 'label' | 'name'> | null
  label?: string
  full?: boolean
  strong?: boolean
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <span
    data-testid="round-badge"
    :class="
      cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md border border-transparent bg-secondary whitespace-nowrap text-secondary-foreground',
        strong ? 'px-2 py-0.5 text-[13px] font-semibold' : 'px-1.5 py-px text-[11.5px] font-medium',
        props.class,
      )
    "
  >
    <span>{{ round?.label ?? label }}</span>
    <template v-if="full && round">
      <span class="text-muted-foreground" aria-hidden="true">·</span>
      <span>{{ round.name }}</span>
    </template>
  </span>
</template>
