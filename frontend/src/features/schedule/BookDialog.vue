<script setup lang="ts">
import { InfoIcon, UsersIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { useSchedulable } from '@/api/queries'
import type { Interviewer, ScheduleSuggestion, SessionMode } from '@/api/types'
import RoundBadge from '@/components/common/RoundBadge.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatDate, formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

import { useBookSession } from './booking'
import BookingFields from './BookingFields.vue'

/**
 * Turn a suggested slot into a scheduled session (확정 일정). The round comes first: 1차 lists those
 * who passed screening, N차 those a person passed in round N-1. Mode starts at the round's default.
 */
const props = defineProps<{ suggestion: ScheduleSuggestion | null; interviewers: Interviewer[] }>()
const emit = defineEmits<{ close: [] }>()

const apps = useSchedulable(() => props.suggestion !== null)
const { create, book } = useBookSession()
const position = ref<number | null>(null)
const appId = ref('')
const mode = ref<SessionMode>('remote')
const lead = ref('')
const panel = computed(() => (props.suggestion ? props.interviewers.filter((i) => props.suggestion!.interviewer_ids.includes(i.id)) : []))
const description = computed(() =>
  props.suggestion
    ? `${formatDate(props.suggestion.start_at)} ${formatTime(props.suggestion.start_at)}–${formatTime(props.suggestion.end_at)} · 면접관 ${panel.value.map((p) => p.name).join(', ')}`
    : '',
)

/** Rounds people are waiting for, in order, with how many wait. */
const rounds = computed(() => {
  const m = new Map<number, { position: number; label: string; count: number }>()
  for (const a of apps.data ?? []) {
    const r = m.get(a.round.position) ?? { position: a.round.position, label: a.round.label, count: 0 }
    r.count += 1
    m.set(a.round.position, r)
  }
  return [...m.values()].sort((a, b) => a.position - b.position)
})
watch(
  rounds,
  (r) => {
    if (position.value === null || !r.some((x) => x.position === position.value)) position.value = r[0]?.position ?? null
  },
  { immediate: true },
)
const waiting = computed(() => (apps.data ?? []).filter((a) => a.round.position === position.value))
const picked = computed(() => waiting.value.find((a) => a.application_id === appId.value))
const guidance = computed(() => {
  const p = position.value
  if (p === null) return ''
  return p === 1 ? `서류 통과 ${waiting.value.length}명 대기` : `${p - 1}차 합격 ${waiting.value.length}명 대기`
})
const short = computed(() => (picked.value ? panel.value.length < picked.value.recommended_interviewers : false))

function pickRound(v: unknown) {
  position.value = Number(v)
  appId.value = ''
}
function pickApp(v: unknown) {
  appId.value = typeof v === 'string' ? v : ''
  if (picked.value) mode.value = picked.value.mode
}

function submit() {
  const slot = props.suggestion
  const app = picked.value
  if (!slot || !app) return
  book({ applicationId: app.application_id, roundId: app.round.id, slot, panel: panel.value, mode: mode.value, lead: lead.value }, () => emit('close'))
}
</script>

<template>
  <Dialog :open="suggestion !== null" @update:open="(o) => !o && emit('close')">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>면접 잡기</DialogTitle>
        <DialogDescription>{{ description }}</DialogDescription>
      </DialogHeader>
      <div class="min-w-0 space-y-4">
        <div class="space-y-1.5">
          <Label>차수</Label>
          <p v-if="apps.data && rounds.length === 0" class="text-xs text-muted-foreground">면접을 잡을 지원자가 없습니다. 서류 통과나 이전 차수 합격이 먼저입니다.</p>
          <div v-else class="flex flex-wrap items-center gap-3">
            <Segmented :model-value="String(position ?? '')" aria-label="차수 선택" data-testid="book-round" @update:model-value="pickRound">
              <SegmentedItem v-for="r in rounds" :key="r.position" :value="String(r.position)">
                {{ r.label }}
                <span class="text-[11.5px] text-muted-foreground tabular">{{ r.count }}</span>
              </SegmentedItem>
            </Segmented>
            <span v-if="guidance" class="inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid="book-guidance">
              <InfoIcon class="size-3.5" aria-hidden="true" />
              {{ guidance }}
            </span>
          </div>
        </div>
        <div class="min-w-0 space-y-1.5">
          <Label>지원자</Label>
          <Select :model-value="appId" :disabled="waiting.length === 0" @update:model-value="pickApp">
            <SelectTrigger aria-label="지원자 선택" class="min-w-0 [&>span]:min-w-0">
              <SelectValue :placeholder="!apps.data ? '불러오는 중…' : position === 1 ? '서류 통과 지원자 선택' : `${(position ?? 2) - 1}차 합격자 선택`" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="a in waiting" :key="a.application_id" :value="a.application_id">
                {{ a.candidate.pseudonym }} · {{ a.posting.title }} · 적합도 {{ a.fit_score }}
              </SelectItem>
            </SelectContent>
          </Select>
          <p v-if="picked" class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <RoundBadge :round="picked.round" full />
            <span :class="cn('inline-flex items-center gap-1', short && 'text-warning')">
              <UsersIcon class="size-3.5" aria-hidden="true" />
              권장 면접관 {{ picked.recommended_interviewers }}명 · 이 시간 패널 {{ panel.length }}명
            </span>
          </p>
        </div>
        <BookingFields v-model:mode="mode" v-model:lead="lead" :panel="panel" />
      </div>
      <DialogFooter>
        <Button variant="outline" @click="emit('close')">취소</Button>
        <Button :disabled="!picked || create.isPending" @click="submit">{{ create.isPending ? '잡는 중…' : '일정 확정' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
