<script setup lang="ts">
import { CircleAlertIcon, QuoteIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { Evaluation } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Badge } from '@/components/ui/badge'
import { LOW_CONFIDENCE } from '@/lib/scoring'
import { formatScore } from '@/lib/utils'

import ConfidenceMeter from './ConfidenceMeter.vue'

/** AI scores per competency with the quoted evidence for every item score (FR-07: 근거 인용 필수). */
const props = defineProps<{ ev: Evaluation }>()

const blocks = computed(() => {
  const qaById = new Map(props.ev.qa_items.map((q) => [q.id, q]))
  return (props.ev.competency_set?.competencies ?? []).map((c) => ({
    name: c.name,
    summary: props.ev.ai.summary.find((s) => s.competency === c.name),
    items: props.ev.ai.scores.filter((s) => s.competency === c.name).map((s) => ({ s, qa: qaById.get(s.qa_item_id) })),
  }))
})
</script>

<template>
  <div class="space-y-4">
    <div v-for="b in blocks" :key="b.name" class="rounded-lg border p-4">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h4 class="text-sm font-semibold">{{ b.name }}</h4>
        <template v-if="b.summary">
          <span class="text-sm">
            <span class="text-muted-foreground">AI </span>
            <span class="font-semibold tabular">{{ formatScore(b.summary.score) }}</span>
            <span class="text-muted-foreground"> / 5 · 답변 {{ b.summary.item_count }}개</span>
          </span>
          <ConfidenceMeter :value="b.summary.confidence" />
          <Badge v-if="b.summary.confidence < LOW_CONFIDENCE" variant="warning">
            <CircleAlertIcon />
            면접관 검토 필요
          </Badge>
        </template>
        <span v-else class="text-xs text-muted-foreground">이 역량을 다룬 답변이 없어 AI가 채점하지 않았습니다 (근거 없는 점수는 저장하지 않음)</span>
      </div>
      <ul v-if="b.items.length > 0" class="mt-3 space-y-2.5">
        <li v-for="{ s, qa } in b.items" :key="s.id" class="flex gap-3">
          <span class="mt-0.5 w-9 shrink-0 font-mono text-[11px] font-semibold text-muted-foreground">Q{{ qa?.seq }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span class="text-[13px] font-semibold tabular">{{ s.score }}점</span>
              <ConfidenceMeter v-if="s.confidence != null" :value="s.confidence" />
            </div>
            <blockquote class="mt-1.5 flex gap-1.5 border-l-2 border-brand-border pl-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
              <QuoteIcon class="mt-1 size-3 shrink-0" aria-hidden="true" />
              <DeidText :text="s.evidence ?? ''" />
            </blockquote>
            <p v-if="qa" class="mt-1 truncate text-[11.5px] text-muted-foreground/80">질문: {{ qa.question }}</p>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>
