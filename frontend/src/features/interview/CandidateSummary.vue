<script setup lang="ts">
import { ChevronDownIcon, HistoryIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import type { CandidateCard } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import FitRing from '@/components/common/FitRing.vue'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import ScreeningBadge from '@/components/common/ScreeningBadge.vue'
import { Badge } from '@/components/ui/badge'
import { parseRationale } from '@/lib/labels'
import { formatDate } from '@/lib/time'
import { cn } from '@/lib/utils'

const props = defineProps<{ card: CandidateCard }>()
const open = ref(false)
const r = computed(() => (props.card.screening ? parseRationale(props.card.screening.rationale) : null))
const p = computed(() => props.card.profile)
const canExpand = computed(() => {
  const x = r.value
  return Boolean(x) && (x!.strengths.length > 2 || x!.concerns.length > 1 || (p.value?.experience.length ?? 0) > 0)
})
const history = computed(() =>
  props.card.previous_sessions.length > 0
    ? `이전 면접 ${props.card.previous_sessions.length}회 (${props.card.previous_sessions.map((s) => (s.ended_at ? formatDate(s.ended_at) : '')).join(', ')})`
    : '이전 면접 기록 없음',
)
</script>

<template>
  <section aria-label="지원자 요약" class="space-y-3">
    <div class="flex items-center gap-3">
      <FitRing v-if="card.screening" :value="card.screening.fit_score" :size="48" />
      <div class="min-w-0">
        <Pseudonym :value="card.candidate.pseudonym" size="lg" />
        <div class="mt-1 flex flex-wrap items-center gap-1.5">
          <ScreeningBadge v-if="card.screening" :status="card.screening.status" />
          <Badge v-if="p" variant="outline">경력 {{ p.years_experience }}년</Badge>
        </div>
      </div>
    </div>

    <template v-if="p">
      <p class="text-[13px] leading-relaxed"><DeidText :text="p.summary" /></p>
      <div class="flex flex-wrap gap-1">
        <span v-for="s in p.skills" :key="s" class="rounded-md bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">{{ s }}</span>
      </div>
    </template>

    <div v-if="r" class="rounded-lg border bg-subtle p-3">
      <p class="mb-2 text-[11.5px] font-medium text-muted-foreground">서류 선별 근거 요약 · 참고용</p>
      <ul class="space-y-1.5 text-[12.5px] leading-snug">
        <li v-for="s in open ? r.strengths : r.strengths.slice(0, 2)" :key="s" class="flex gap-1.5">
          <span class="mt-0.5 text-success" aria-label="강점">+</span>
          <DeidText :text="s" />
        </li>
        <li v-for="s in open ? r.concerns : r.concerns.slice(0, 1)" :key="s" class="flex gap-1.5 text-muted-foreground">
          <span class="mt-0.5 text-warning" aria-label="확인 필요">−</span>
          <DeidText :text="s" />
        </li>
      </ul>
      <button
        v-if="canExpand"
        type="button"
        class="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        @click="open = !open"
      >
        <ChevronDownIcon :class="cn('size-3.5 transition-transform', open && 'rotate-180')" aria-hidden="true" />
        {{ open ? '접기' : '경력·학력 더 보기' }}
      </button>
      <div v-if="open && p" class="mt-3 space-y-2 border-t pt-3 text-[12.5px]">
        <div v-for="e in p.experience" :key="e.company + e.period">
          <div class="font-medium"><DeidText :text="e.company" /> · {{ e.role }}</div>
          <div class="text-[11.5px] text-muted-foreground">{{ e.period }}</div>
        </div>
        <div v-for="e in p.education" :key="e.school" class="text-muted-foreground"><DeidText :text="e.school" /> {{ e.degree }} · {{ e.major }}</div>
      </div>
    </div>

    <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
      <HistoryIcon class="size-3.5" aria-hidden="true" />
      {{ history }}
    </div>
    <PrivacyNote />
  </section>
</template>
