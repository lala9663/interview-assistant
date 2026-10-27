<script setup lang="ts">
import { AwardIcon, CheckIcon, ClockIcon, HourglassIcon, PauseIcon, XIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { ProgressStep } from '@/api/types'
import { stepStatusLabel } from '@/lib/labels'
import { formatDateShort } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * 서류 → each round → 최종, left to right, each step with its result and date. Round names come
 * from the posting's 전형 ("1차 직무 면접"); the dot carries the status color, the step itself
 * stays neutral like every round badge.
 */
const props = defineProps<{ steps: ProgressStep[] }>()

const items = computed(() =>
  props.steps.map((s) => ({
    ...s,
    title: s.kind === 'screening' ? '서류' : s.kind === 'final' ? '최종' : s.round!.label,
    subtitle: s.kind === 'round' ? s.round!.name : s.kind === 'screening' ? '선별' : '합격 후보',
    text: s.status === null ? '' : stepStatusLabel(s),
  })),
)
const tone = (s: ProgressStep) =>
  s.status === null
    ? 'border-border bg-card text-muted-foreground/60'
    : s.status === 'passed'
      ? 'border-success bg-[color-mix(in_oklch,var(--success)_14%,transparent)] text-success'
      : s.status === 'rejected'
        ? 'border-danger bg-[color-mix(in_oklch,var(--danger)_12%,transparent)] text-danger'
        : s.status === 'hold'
          ? 'border-warning bg-[color-mix(in_oklch,var(--warning)_14%,transparent)] text-warning'
          : s.status === 'in_progress'
            ? 'border-live bg-[color-mix(in_oklch,var(--live)_12%,transparent)] text-live'
            : s.status === 'deciding'
              ? 'border-brand-border bg-brand-soft text-brand'
              : 'border-border bg-muted text-muted-foreground'
const textTone = (s: ProgressStep) =>
  s.status === 'passed' ? 'text-success' : s.status === 'rejected' ? 'text-danger' : s.status === 'hold' ? 'text-warning' : s.status === 'in_progress' ? 'text-live' : 'text-muted-foreground'
</script>

<template>
  <ol class="flex items-start" aria-label="진행 단계" data-testid="round-stepper">
    <li v-for="(s, i) in items" :key="i" class="relative min-w-0 flex-1 text-center" :aria-current="s.status !== null && s.status !== 'passed' ? 'step' : undefined">
      <span
        v-if="i < items.length - 1"
        :class="cn('absolute top-3.5 left-1/2 h-px w-full', items[i + 1]!.status !== null ? 'bg-foreground/25' : 'bg-border')"
        aria-hidden="true"
      ></span>
      <span :class="cn('relative mx-auto flex size-7 items-center justify-center rounded-full border', tone(s))" aria-hidden="true">
        <AwardIcon v-if="s.kind === 'final' && s.status === 'passed'" class="size-3.5" />
        <CheckIcon v-else-if="s.status === 'passed'" class="size-3.5" />
        <XIcon v-else-if="s.status === 'rejected'" class="size-3.5" />
        <PauseIcon v-else-if="s.status === 'hold'" class="size-3.5" />
        <span v-else-if="s.status === 'in_progress'" class="size-2 animate-live rounded-full bg-live" />
        <ClockIcon v-else-if="s.status === 'scheduled'" class="size-3.5" />
        <HourglassIcon v-else-if="s.status === 'evaluating' || s.status === 'deciding'" class="size-3.5" />
        <span v-else class="size-1.5 rounded-full bg-current" />
      </span>
      <p class="mt-1.5 truncate px-1 text-[12px] font-semibold">{{ s.title }}</p>
      <p class="truncate px-1 text-[11px] text-muted-foreground">{{ s.subtitle }}</p>
      <p :class="cn('truncate px-1 text-[11.5px] font-medium', textTone(s))">{{ s.text || '–' }}</p>
      <p class="truncate px-1 text-[11px] text-muted-foreground tabular">{{ s.at ? formatDateShort(s.at) : '' }}</p>
    </li>
  </ol>
</template>
