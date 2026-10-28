<script setup lang="ts">
import { CalendarCheck2Icon, SearchXIcon, UsersIcon } from '@lucide/vue'
import { RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import { computed, ref } from 'vue'

import { useInterviewers, useScheduleSuggestions } from '@/api/queries'
import type { SchedulableApplication, ScheduleSuggestion, SessionMode } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import RoundBadge from '@/components/common/RoundBadge.vue'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { addDays, formatDate, formatDuration, formatTime, kstDayInput, parseKstDayInput } from '@/lib/time'
import { cn } from '@/lib/utils'

import { useBookSession } from './booking'
import BookingFields from './BookingFields.vue'

/**
 * 면접 잡기 for one application whose round is already fixed (the one it waits for, from 지원자 상세).
 * The panel starts at the round's recommended size, the posting's job family first; the slots are
 * the times the whole panel is free. Mode starts at the round's default.
 */
const props = defineProps<{ application: SchedulableApplication | null }>()
const emit = defineEmits<{ close: [] }>()

const interviewers = useInterviewers()
const { create, book } = useBookSession()
const picked = ref<string[] | null>(null)
const duration = ref(60)
const today = new Date()
const fromDay = ref(kstDayInput(today))
const toDay = ref(kstDayInput(addDays(today, 13)))
const slotKey = ref('')
const mode = ref<SessionMode>(props.application?.mode ?? 'remote')
const lead = ref('')

const ordered = computed(() => {
  const all = interviewers.data ?? []
  const family = props.application?.posting.job_family
  return [...all.filter((i) => i.job_family === family), ...all.filter((i) => i.job_family !== family)]
})
const recommended = computed(() => props.application?.recommended_interviewers ?? 0)
const selected = computed(() => picked.value ?? ordered.value.slice(0, recommended.value).map((i) => i.id))
const short = computed(() => selected.value.length < recommended.value)

const range = computed(() => {
  const from = parseKstDayInput(fromDay.value)
  const to = parseKstDayInput(toDay.value)
  return from && to && from <= to ? { from: from.toISOString(), to: addDays(to, 1).toISOString() } : null
})
const suggestions = useScheduleSuggestions(() => ({
  // No interviewer ids keeps the query from running: nobody picked, or the range is backwards.
  interviewer_ids: range.value ? selected.value : [],
  from: range.value?.from ?? '',
  to: range.value?.to ?? '',
  duration_minutes: duration.value,
}))
const keyOf = (s: ScheduleSuggestion) => `${s.start_at}|${s.interviewer_ids.join()}`
// Slots of the previous panel or range stay on screen while the new ones load; none can be booked.
const slot = computed(() => (suggestions.isPlaceholderData ? null : (suggestions.data?.find((s) => keyOf(s) === slotKey.value) ?? null)))
const panel = computed(() => ordered.value.filter((i) => (slot.value?.interviewer_ids ?? selected.value).includes(i.id)))

function toggle(id: string) {
  picked.value = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id]
}

function submit() {
  const app = props.application
  const s = slot.value
  if (!app || !s) return
  book({ applicationId: app.application_id, roundId: app.round.id, slot: s, panel: panel.value, mode: mode.value, lead: lead.value }, () => emit('close'))
}
</script>

<template>
  <Dialog :open="application !== null" @update:open="(o) => !o && emit('close')">
    <DialogContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>면접 잡기</DialogTitle>
        <DialogDescription v-if="application" class="flex min-w-0 flex-wrap items-center gap-1.5" data-testid="book-fixed">
          <Pseudonym :value="application.candidate.pseudonym" size="sm" class="text-foreground" />
          <RoundBadge :round="application.round" full />
          <span class="min-w-0 truncate">{{ application.posting.title }}</span>
        </DialogDescription>
      </DialogHeader>

      <div class="grid min-w-0 gap-5 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
        <section class="min-w-0 space-y-1.5">
          <div class="flex items-center justify-between gap-2">
            <h3 class="text-[13px] leading-none font-medium">면접관</h3>
            <span :class="cn('inline-flex items-center gap-1 text-xs text-muted-foreground tabular', short && 'text-warning')" data-testid="book-panel-count">
              <UsersIcon class="size-3.5" aria-hidden="true" />
              {{ selected.length }}명 · 권장 {{ recommended }}명
            </span>
          </div>
          <ErrorState v-if="interviewers.isError" :error="interviewers.error" class="py-6" @retry="interviewers.refetch()" />
          <Skeleton v-else-if="!interviewers.data" class="h-40" />
          <ul v-else class="max-h-64 space-y-0.5 overflow-y-auto scrollbar-thin">
            <li v-for="iv in ordered" :key="iv.id">
              <label class="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-subtle">
                <Checkbox :model-value="selected.includes(iv.id)" :aria-label="`${iv.name} 선택`" @update:model-value="toggle(iv.id)" />
                <span class="min-w-0 flex-1">
                  <span class="block text-[13px] font-medium">{{ iv.name }}</span>
                  <span class="block truncate text-[11.5px] text-muted-foreground">{{ iv.job_family }} · {{ iv.department }}</span>
                </span>
              </label>
            </li>
          </ul>
        </section>

        <div class="min-w-0 space-y-4">
          <div class="flex flex-wrap gap-x-5 gap-y-3">
            <div class="space-y-1.5">
              <Label>면접 길이</Label>
              <Segmented :model-value="String(duration)" aria-label="면접 길이" @update:model-value="(v) => (duration = Number(v))">
                <SegmentedItem v-for="m in [60, 90, 120]" :key="m" :value="String(m)">{{ formatDuration(m) }}</SegmentedItem>
              </Segmented>
            </div>
            <div class="min-w-0 flex-1 basis-64 space-y-1.5">
              <Label>기간</Label>
              <div class="flex max-w-80 items-center gap-1.5">
                <Input v-model="fromDay" type="date" :max="toDay" aria-label="시작 날짜" class="h-8 flex-1 px-2 text-[13px] tabular" />
                <span class="text-muted-foreground" aria-hidden="true">–</span>
                <Input v-model="toDay" type="date" :min="fromDay" aria-label="끝 날짜" class="h-8 flex-1 px-2 text-[13px] tabular" />
              </div>
            </div>
          </div>

          <section class="space-y-1.5">
            <h3 id="book-slots-label" class="flex items-center gap-1.5 text-[13px] leading-none font-medium">
              <CalendarCheck2Icon class="size-4 text-muted-foreground" aria-hidden="true" />
              함께 비는 시간
            </h3>
            <p v-if="selected.length === 0" class="text-[13px] text-muted-foreground">면접관을 선택하세요.</p>
            <p v-else-if="!range" class="text-[13px] text-muted-foreground">끝 날짜가 시작 날짜보다 빠릅니다.</p>
            <ErrorState v-else-if="suggestions.isError" :error="suggestions.error" class="py-6" @retry="suggestions.refetch()" />
            <Skeleton v-else-if="!suggestions.data" class="h-32" />
            <EmptyState
              v-else-if="suggestions.data.length === 0"
              compact
              :icon="SearchXIcon"
              title="함께 비는 시간이 없습니다"
              description="면접관을 바꾸거나 기간을 늘려 보세요."
            />
            <RadioGroupRoot
              v-else
              v-model="slotKey"
              aria-labelledby="book-slots-label"
              :class="cn('grid max-h-56 gap-1.5 overflow-y-auto scrollbar-thin sm:grid-cols-2', suggestions.isPlaceholderData && 'opacity-60')"
            >
              <RadioGroupItem
                v-for="s in suggestions.data"
                :key="keyOf(s)"
                :value="keyOf(s)"
                class="rounded-lg border px-2.5 py-2 text-left text-[13px] font-medium tabular transition-colors outline-none hover:bg-subtle focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=checked]:border-ring data-[state=checked]:bg-brand-soft"
              >
                {{ formatDate(s.start_at) }} {{ formatTime(s.start_at) }}–{{ formatTime(s.end_at) }}
              </RadioGroupItem>
            </RadioGroupRoot>
          </section>
        </div>
      </div>

      <BookingFields v-model:mode="mode" v-model:lead="lead" :panel="panel" />
      <DialogFooter>
        <Button variant="outline" @click="emit('close')">취소</Button>
        <Button :disabled="!slot || create.isPending" @click="submit">{{ create.isPending ? '잡는 중…' : '일정 확정' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
