<script setup lang="ts">
import { CheckIcon, ClockIcon, HourglassIcon, PauseIcon, XIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { ProgressStep } from '@/api/types'
import { stepLabel, stepStatusLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * The short trail of a row: "서류 ✓ · 1차 ✓ · 2차 ●". ✓ passed, ● in progress (live red), clock
 * scheduled, pause hold, ✕ rejected, hourglass waiting on scores or a decision. Steps not reached
 * are muted; 최종 shows only once reached.
 */
const props = defineProps<{ steps: ProgressStep[] }>()
const shown = computed(() => props.steps.filter((s) => s.kind !== 'final' || s.status === 'passed'))
const spoken = computed(() => shown.value.map((s) => `${stepLabel(s)} ${stepStatusLabel(s)}`).join(', '))
</script>

<template>
  <span class="inline-flex items-center gap-1 text-[12px] whitespace-nowrap" :aria-label="spoken" role="img" data-testid="progress-trail">
    <template v-for="(s, i) in shown" :key="i">
      <span v-if="i > 0" class="text-muted-foreground/50" aria-hidden="true">·</span>
      <span :class="cn('inline-flex items-center gap-0.5', s.status === null ? 'text-muted-foreground/50' : 'text-foreground/85')" aria-hidden="true">
        {{ stepLabel(s) }}
        <CheckIcon v-if="s.status === 'passed'" class="size-3 text-success" />
        <span v-else-if="s.status === 'in_progress'" class="mx-0.5 size-1.5 rounded-full bg-live" />
        <ClockIcon v-else-if="s.status === 'scheduled'" class="size-3 text-muted-foreground" />
        <PauseIcon v-else-if="s.status === 'hold'" class="size-3 text-warning" />
        <XIcon v-else-if="s.status === 'rejected'" class="size-3 text-danger" />
        <HourglassIcon v-else-if="s.status === 'evaluating' || s.status === 'deciding'" class="size-3 text-muted-foreground" />
      </span>
    </template>
  </span>
</template>
