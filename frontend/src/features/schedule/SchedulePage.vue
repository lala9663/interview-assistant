<script setup lang="ts">
import { CalendarCheck2Icon, ChevronLeftIcon, ChevronRightIcon, MousePointerClickIcon, SearchXIcon, UsersIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import { useAvailabilities, useAvailabilityMutations, useInterviewers, useMe, useScheduleSuggestions } from '@/api/queries'
import type { Availability, ScheduleSuggestion } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { addDays, addMinutes, formatDate, formatDuration, formatTime, startOfKstWeek } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { cn } from '@/lib/utils'

import BookDialog from './BookDialog.vue'
import { colorOf } from './grid'
import WeekGrid from './WeekGrid.vue'

const interviewers = useInterviewers()
const me = useMe()
const weekOffset = ref(0)
const family = ref('공정개발')
const picked = ref<string[] | null>(null)
const duration = ref(60)
const minSel = ref<number | null>(null)
const highlight = ref<ScheduleSuggestion | null>(null)
const booking = ref<ScheduleSuggestion | null>(null)
const editMine = ref(false)
const { create, remove } = useAvailabilityMutations()

const weekStart = computed(() => addDays(startOfKstWeek(new Date()), weekOffset.value * 7))
const from = computed(() => weekStart.value.toISOString())
const to = computed(() => addDays(weekStart.value, 5).toISOString())
const avail = useAvailabilities(from, to)

const all = computed(() => interviewers.data ?? [])
const families = computed(() => [...new Set(all.value.map((i) => i.job_family ?? '기타'))])
const shown = computed(() => (family.value === '전체' ? all.value : all.value.filter((i) => i.job_family === family.value)))
const selected = computed(() => picked.value ?? shown.value.filter((i) => i.job_family === family.value).map((i) => i.id))
const minCount = computed(() => Math.min(minSel.value ?? selected.value.length, selected.value.length))
const suggestions = useScheduleSuggestions(() => ({
  interviewer_ids: selected.value,
  from: from.value,
  to: addDays(weekStart.value, 12).toISOString(),
  duration_minutes: duration.value,
  min_interviewers: minCount.value,
}))
const canEditMine = computed(() => Boolean(me.data && selected.value.includes(me.data.id)))
const nameOf = (id: string) => all.value.find((i) => i.id === id)?.name

function focus(s: ScheduleSuggestion | null) {
  highlight.value = s
  if (s) weekOffset.value = Math.round((startOfKstWeek(s.start_at).getTime() - startOfKstWeek(new Date()).getTime()) / (7 * 86_400_000))
}
function book(s: ScheduleSuggestion) {
  focus(s)
  booking.value = s
}
function toggle(id: string) {
  picked.value = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id]
  highlight.value = null
}
function onFamily(v: unknown) {
  if (typeof v !== 'string') return
  family.value = v
  picked.value = null
  highlight.value = null
}
function onCellClick(start: Date) {
  if (!me.data) return
  create.mutate(
    { interviewer_id: me.data.id, start_at: start.toISOString(), end_at: addMinutes(start, 60).toISOString() },
    { onError: toastError('가용 시간을 추가하지 못했습니다') },
  )
}
const onBlockClick = (a: Availability) => remove.mutate(a.id)
</script>

<template>
  <Page v-if="interviewers.isError"><ErrorState :error="interviewers.error" @retry="interviewers.refetch()" /></Page>
  <Page v-else>
    <PageHeader eyebrow="FR-09" title="면접관 스케줄" description="면접관 가용 시간(수기 입력)을 겹쳐 보고, 선택한 패널이 함께 비는 시간을 찾아 일정을 잡습니다." />
    <div class="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <div class="flex flex-col gap-4">
        <Card>
          <CardContent class="space-y-3 pt-4">
            <div class="flex items-center justify-between">
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold">
                <UsersIcon class="size-4 text-muted-foreground" aria-hidden="true" />
                면접관
              </h2>
              <span class="text-xs text-muted-foreground tabular">{{ selected.length }}명 선택</span>
            </div>
            <Select :model-value="family" @update:model-value="onFamily">
              <SelectTrigger class="h-8 text-[13px]" aria-label="직군">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="전체">전체 직군</SelectItem>
                <SelectItem v-for="f in families" :key="f" :value="f">{{ f }}</SelectItem>
              </SelectContent>
            </Select>
            <Skeleton v-if="!interviewers.data" class="h-32" />
            <ul v-else class="space-y-1">
              <li v-for="iv in shown" :key="iv.id">
                <label class="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-subtle">
                  <Checkbox :model-value="selected.includes(iv.id)" :aria-label="`${iv.name} 선택`" @update:model-value="toggle(iv.id)" />
                  <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ background: colorOf(all.findIndex((x) => x.id === iv.id)) }" aria-hidden="true"></span>
                  <span class="min-w-0 flex-1">
                    <span class="block text-[13px] font-medium">
                      {{ iv.name }}<span v-if="iv.id === me.data?.id" class="ml-1 text-xs font-normal text-muted-foreground">(나)</span>
                    </span>
                    <span class="block truncate text-[11.5px] text-muted-foreground">{{ iv.department }}</span>
                  </span>
                </label>
              </li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardContent class="space-y-4 pt-4">
            <h2 class="text-[13px] font-semibold">조건</h2>
            <div class="space-y-1.5">
              <Label class="text-xs text-muted-foreground">면접 길이</Label>
              <Segmented :model-value="String(duration)" aria-label="면접 길이" @update:model-value="(v) => (duration = Number(v))">
                <SegmentedItem v-for="m in [60, 90, 120]" :key="m" :value="String(m)">{{ formatDuration(m) }}</SegmentedItem>
              </Segmented>
            </div>
            <div class="space-y-1.5">
              <Label class="text-xs text-muted-foreground">최소 인원</Label>
              <Select :model-value="String(minCount)" :disabled="selected.length === 0" @update:model-value="(v) => (minSel = Number(v))">
                <SelectTrigger class="h-8 text-[13px]" aria-label="최소 인원">
                  <SelectValue placeholder="면접관을 선택하세요" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="n in selected.length" :key="n" :value="String(n)">
                    {{ n === selected.length ? `선택한 ${n}명 모두` : `${n}명 이상` }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent class="space-y-2 pt-4">
            <h2 class="flex items-center gap-1.5 text-[13px] font-semibold">
              <CalendarCheck2Icon class="size-4 text-muted-foreground" aria-hidden="true" />
              후보 시간
            </h2>
            <p v-if="selected.length === 0" class="text-[13px] text-muted-foreground">면접관을 선택하세요.</p>
            <Skeleton v-else-if="!suggestions.data" class="h-24" />
            <ul v-else-if="suggestions.data.length > 0" class="space-y-1.5">
              <li v-for="s in suggestions.data" :key="s.start_at + s.interviewer_ids.join()">
                <div
                  :class="
                    cn(
                      'flex items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors',
                      highlight?.start_at === s.start_at ? 'border-ring bg-brand-soft' : 'hover:bg-subtle',
                    )
                  "
                >
                  <button type="button" class="min-w-0 flex-1 text-left" @click="focus(highlight?.start_at === s.start_at ? null : s)">
                    <span class="block text-[13px] font-medium tabular">{{ formatDate(s.start_at) }} {{ formatTime(s.start_at) }}–{{ formatTime(s.end_at) }}</span>
                    <span class="block truncate text-[11.5px] text-muted-foreground">{{ s.interviewer_ids.map(nameOf).join(', ') }}</span>
                  </button>
                  <Button size="xs" :variant="highlight?.start_at === s.start_at ? 'default' : 'outline'" @click="book(s)">면접 잡기</Button>
                </div>
              </li>
            </ul>
            <EmptyState v-else compact :icon="SearchXIcon" title="함께 비는 시간이 없습니다" description="최소 인원을 낮추거나 다른 주를 보세요." />
          </CardContent>
        </Card>
      </div>

      <Card class="min-w-0">
        <div class="flex flex-wrap items-center gap-3 border-b px-4 py-3">
          <div class="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" aria-label="이전 주" @click="weekOffset -= 1"><ChevronLeftIcon /></Button>
            <Button variant="outline" size="sm" :disabled="weekOffset === 0" @click="weekOffset = 0">이번 주</Button>
            <Button variant="ghost" size="icon-sm" aria-label="다음 주" @click="weekOffset += 1"><ChevronRightIcon /></Button>
          </div>
          <span class="text-sm font-medium tabular">{{ formatDate(weekStart) }} – {{ formatDate(addDays(weekStart, 4)) }}</span>
          <div class="ml-auto flex items-center gap-4">
            <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span class="size-3 rounded-[3px] border-2 border-dashed border-ring bg-[color-mix(in_oklch,var(--ring)_14%,transparent)]" aria-hidden="true"></span>
              공통 빈 시간
            </span>
            <div class="flex items-center gap-2">
              <Switch id="edit-mine" v-model="editMine" :disabled="!canEditMine" />
              <Label for="edit-mine" class="text-xs font-normal text-muted-foreground">내 가용 시간 편집</Label>
            </div>
          </div>
        </div>
        <p v-if="editMine" class="flex items-center gap-1.5 border-b bg-subtle px-4 py-2 text-xs text-muted-foreground">
          <MousePointerClickIcon class="size-3.5" aria-hidden="true" />빈 칸을 누르면 1시간이 추가되고, 내 블록을 누르면 삭제됩니다. 캘린더 연동은 Phase 2입니다.
        </p>
        <div class="p-3">
          <ErrorState v-if="avail.isError" :error="avail.error" @retry="avail.refetch()" />
          <Skeleton v-else-if="!avail.data || !interviewers.data" class="h-[620px]" />
          <WeekGrid
            v-else
            :week-start="weekStart"
            :interviewers="all"
            :selected="selected"
            :availabilities="avail.data"
            :min-count="minCount"
            :highlight="highlight"
            :edit-for="editMine ? (me.data?.id ?? null) : null"
            @cell-click="onCellClick"
            @block-click="onBlockClick"
          />
        </div>
      </Card>
    </div>
    <BookDialog :key="booking?.start_at ?? 'closed'" :suggestion="booking" :interviewers="all" @close="booking = null" />
  </Page>
</template>
