<script setup lang="ts">
import { confidenceLabel, LOW_CONFIDENCE } from '@/lib/scoring'
import { cn } from '@/lib/utils'

defineProps<{ value: number }>()
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-xs text-muted-foreground" :title="`신뢰도 ${value.toFixed(2)}`">
    <span class="h-1.5 w-12 overflow-hidden rounded-full bg-muted" aria-hidden="true">
      <span :class="cn('block h-full rounded-full', value < LOW_CONFIDENCE ? 'bg-warning' : 'bg-series-1')" :style="{ width: `${value * 100}%` }"></span>
    </span>
    <span :class="cn('tabular', value < LOW_CONFIDENCE && 'font-medium text-warning')">신뢰도 {{ confidenceLabel(value) }} {{ value.toFixed(2) }}</span>
  </span>
</template>
