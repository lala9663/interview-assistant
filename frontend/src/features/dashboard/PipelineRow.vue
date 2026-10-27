<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import type { PipelineRow } from '@/api/types'
import { POSTING_STATUS_LABEL } from '@/lib/labels'

/**
 * One posting's funnel: 서류 → 1차 → 2차 … → 최종, as many round columns as the posting has. Each
 * column counts the applications that reached it; the line under it says where they are now.
 */
const props = defineProps<{ row: PipelineRow }>()

const FUNNEL = ['var(--funnel-1)', 'var(--funnel-2)', 'var(--funnel-3)', 'var(--funnel-4)']

const total = computed(() => Math.max(1, props.row.counts.applications))
const columns = computed(() => {
  const c = props.row.counts
  const cols = [
    { key: 'screening', label: '서류', v: c.applications, note: `통과 ${c.passed} · 보류 ${c.hold}` },
    ...c.rounds.map((r) => ({
      key: r.round.id,
      label: r.round.label,
      v: r.reached,
      note: `진행 ${r.scheduled + r.in_progress + r.evaluating + r.deciding} · 합격 ${r.passed}`,
      title: `${r.round.label} ${r.round.name}: 일정 대기 ${r.waiting}, 예정 ${r.scheduled}, 진행 중 ${r.in_progress}, 평가 대기 ${r.evaluating}, 결정 대기 ${r.deciding}, 합격 ${r.passed}, 보류 ${r.hold}, 불합격 ${r.rejected}`,
    })),
    { key: 'final', label: '최종', v: c.final, note: '최종 합격 후보' },
  ]
  return cols.map((col, i) => ({ ...col, pct: (col.v / total.value) * 100, color: FUNNEL[Math.min(i, FUNNEL.length - 1)] }))
})
</script>

<template>
  <div class="grid grid-cols-1 gap-3 py-4 first:pt-1 last:pb-1 md:grid-cols-[minmax(0,200px)_1fr] md:gap-6" data-testid="pipeline-row">
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
    <div v-else class="grid gap-3" :style="{ gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))` }">
      <div v-for="(s, i) in columns" :key="s.key" class="min-w-0" :title="'title' in s ? s.title : undefined" :data-testid="`pipeline-${s.label}`">
        <div class="flex items-baseline justify-between gap-1">
          <span class="truncate text-xs text-muted-foreground">{{ s.label }}</span>
          <span v-if="i > 0" class="text-[11px] text-muted-foreground/80 tabular">{{ Math.round(s.pct) }}%</span>
        </div>
        <div class="mt-1 text-lg leading-none font-semibold tabular">{{ s.v }}</div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div class="h-full rounded-full transition-[width] duration-700" :style="{ width: `${s.pct}%`, background: s.color }"></div>
        </div>
        <p class="mt-1.5 truncate text-[11px] text-muted-foreground tabular">{{ s.note }}</p>
      </div>
    </div>
  </div>
</template>
