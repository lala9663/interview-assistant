<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import type { PipelineRow } from '@/api/types'
import { POSTING_STATUS_LABEL } from '@/lib/labels'

const props = defineProps<{ row: PipelineRow }>()

const STAGES = [
  { key: 'applications', label: '지원', color: 'var(--funnel-1)' },
  { key: 'passed', label: '서류 통과', color: 'var(--funnel-2)' },
  { key: 'interview', label: '면접', color: 'var(--funnel-3)' },
  { key: 'evaluated', label: '평가 완료', color: 'var(--funnel-4)' },
] as const

const total = computed(() => Math.max(1, props.row.counts.applications))
const stages = computed(() =>
  STAGES.map((s) => {
    const c = props.row.counts
    const v = s.key === 'interview' ? c.interviewing + c.interviewed : c[s.key]
    return { ...s, v, pct: (v / total.value) * 100 }
  }),
)
</script>

<template>
  <div class="grid grid-cols-1 gap-3 py-4 first:pt-1 last:pb-1 md:grid-cols-[minmax(0,220px)_1fr] md:gap-6">
    <div class="min-w-0">
      <RouterLink :to="`/postings/${row.posting.id}`" class="block truncate text-sm font-medium hover:underline">{{ row.posting.title }}</RouterLink>
      <div class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span>{{ row.posting.job_family }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ POSTING_STATUS_LABEL[row.posting.status] }}</span>
      </div>
    </div>
    <div v-if="row.counts.applications === 0" class="flex items-center text-[13px] text-muted-foreground">
      아직 지원자가 없습니다. 공고를 열면 서류 선별이 시작됩니다.
    </div>
    <div v-else class="grid grid-cols-4 gap-3">
      <div v-for="(s, i) in stages" :key="s.key" class="min-w-0">
        <div class="flex items-baseline justify-between gap-1">
          <span class="truncate text-xs text-muted-foreground">{{ s.label }}</span>
          <span v-if="i > 0" class="text-[11px] text-muted-foreground/80 tabular">{{ Math.round(s.pct) }}%</span>
        </div>
        <div class="mt-1 text-lg leading-none font-semibold tabular">{{ s.v }}</div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div class="h-full rounded-full transition-[width] duration-700" :style="{ width: `${s.pct}%`, background: s.color }"></div>
        </div>
      </div>
    </div>
  </div>
</template>
