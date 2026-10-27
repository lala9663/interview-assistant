<script setup lang="ts">
import { BotIcon, ChevronDownIcon, LockIcon, MessageSquareTextIcon, QuoteIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import type { PreviousRound } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import StepStatusChip from '@/components/common/StepStatusChip.vue'
import { Badge } from '@/components/ui/badge'
import { roundFullName } from '@/lib/labels'
import { formatDate } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * 이전 차수 요약 on the candidate card: points to check (interviewers', and AI's with the answer
 * they rest on) and notes. Earlier scores only when this round's setting shows them; otherwise the
 * server leaves them out and the card says so, so they do not anchor this round.
 */
const props = defineProps<{ previous: PreviousRound }>()
const notesOpen = ref(false)
const title = computed(() => `${roundFullName(props.previous.round)} 요약`)
const fmt = (v: number | null) => (v === null ? '–' : v.toFixed(1))
</script>

<template>
  <section :aria-label="title" class="space-y-2.5 rounded-lg border bg-card p-3" data-testid="previous-round">
    <div class="flex items-center justify-between gap-2">
      <p class="text-[12.5px] font-semibold">{{ title }}</p>
      <StepStatusChip v-if="previous.decision" :status="previous.decision" />
    </div>
    <p class="text-[11.5px] text-muted-foreground">
      {{ previous.session.ended_at ? formatDate(previous.session.ended_at) : '' }} · 질문 {{ previous.qa_count }}개 · 메모 {{ previous.notes.length }}개
    </p>

    <p v-if="!previous.scores_visible" class="flex items-center gap-1.5 rounded-md bg-subtle px-2 py-1.5 text-[11.5px] text-muted-foreground" data-testid="scores-hidden">
      <LockIcon class="size-3.5 shrink-0" aria-hidden="true" />
      {{ previous.round.label }} 점수 숨김 (공고 설정)
    </p>
    <div v-else class="space-y-1.5" data-testid="scores-visible">
      <table class="w-full text-[11.5px]">
        <thead>
          <tr class="text-left text-muted-foreground">
            <th class="py-0.5 font-medium">{{ previous.round.label }} 점수</th>
            <th class="py-0.5 text-right font-medium">면접관</th>
            <th class="py-0.5 text-right font-medium">AI 참고</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in previous.scores ?? []" :key="s.competency">
            <td class="truncate py-0.5 pr-2">{{ s.competency }}</td>
            <td class="py-0.5 text-right font-semibold tabular">{{ fmt(s.interviewer_mean) }}</td>
            <td class="py-0.5 text-right text-muted-foreground tabular">{{ fmt(s.ai_mean) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="previous.decision_reason" class="text-[11.5px] leading-snug text-muted-foreground">
        결정 사유: <DeidText :text="previous.decision_reason" />
      </p>
    </div>

    <div>
      <p class="mb-1.5 text-[11.5px] font-medium text-muted-foreground">확인이 필요한 점 {{ previous.check_points.length }}</p>
      <p v-if="previous.check_points.length === 0" class="text-[12px] text-muted-foreground/80">남긴 점이 없습니다.</p>
      <ul class="space-y-2">
        <li v-for="p in previous.check_points" :key="p.id" class="text-[12.5px] leading-snug">
          <div class="mb-0.5 flex flex-wrap items-center gap-1">
            <Badge v-if="p.source === 'ai'" variant="brand" class="py-0 text-[10.5px]"><BotIcon aria-hidden="true" />AI</Badge>
            <Badge v-else variant="outline" class="py-0 text-[10.5px]">{{ p.author_name }}</Badge>
            <span v-if="p.competency" class="text-[11px] text-muted-foreground">{{ p.competency }}</span>
          </div>
          <DeidText :text="p.text" />
          <p v-if="p.evidence" class="mt-1 flex gap-1 border-l-2 pl-2 text-[11.5px] text-muted-foreground">
            <QuoteIcon class="mt-0.5 size-3 shrink-0" aria-label="근거" />
            <DeidText :text="p.evidence" />
          </p>
        </li>
      </ul>
    </div>

    <div v-if="previous.notes.length > 0">
      <button type="button" class="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" :aria-expanded="notesOpen" @click="notesOpen = !notesOpen">
        <MessageSquareTextIcon class="size-3.5" aria-hidden="true" />
        메모 {{ previous.notes.length }}개
        <ChevronDownIcon :class="cn('size-3.5 transition-transform', notesOpen && 'rotate-180')" aria-hidden="true" />
      </button>
      <ul v-if="notesOpen" class="mt-1.5 space-y-1.5">
        <li v-for="n in previous.notes" :key="n.id" class="text-[12px] leading-snug">
          <span class="text-muted-foreground">{{ n.author_name }} · </span>
          <DeidText :text="n.content" />
        </li>
      </ul>
    </div>
  </section>
</template>
