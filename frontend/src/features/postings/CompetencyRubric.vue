<script setup lang="ts">
import { BARS_LEVELS, type Competency } from '@/api/types'

import { LEVEL_HINT } from './competency-utils'

/** Read-only rubric: one card per competency, BARS levels 1-5 as columns on wide screens. */
defineProps<{ competencies: readonly Competency[]; newNames?: Set<string> }>()
</script>

<template>
  <div class="space-y-3">
    <div v-for="c in competencies" :key="c.name" class="rounded-xl border bg-card">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b px-4 py-3">
        <h3 class="text-sm font-semibold">{{ c.name }}</h3>
        <span v-if="newNames?.has(c.name)" class="rounded bg-brand-soft px-1.5 py-0.5 text-[11px] font-medium text-brand">확정본 대비 추가</span>
        <p class="text-[13px] text-muted-foreground">{{ c.description }}</p>
      </div>
      <ol class="grid grid-cols-1 divide-y md:grid-cols-5 md:divide-x md:divide-y-0">
        <li v-for="l in BARS_LEVELS" :key="l" class="px-4 py-3">
          <p class="mb-1 flex items-baseline gap-1.5">
            <span class="text-[15px] font-semibold tabular">{{ l }}</span>
            <span class="text-[11px] text-muted-foreground">{{ LEVEL_HINT[l] }}</span>
          </p>
          <p class="text-[12.5px] leading-relaxed text-muted-foreground">{{ c.bars[l] }}</p>
        </li>
      </ol>
    </div>
  </div>
</template>
