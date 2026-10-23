<script setup lang="ts">
import { computed } from 'vue'

import type { Availability, Interviewer, ScheduleSuggestion } from '@/api/types'
import { Tooltip } from '@/components/ui/tooltip'
import { availabilityByInterviewer, commonFreeIntervals } from '@/lib/schedule'
import { addDays, addMinutes, formatDateShort, formatTime, isSameKstDay, kstMinuteOfDay, startOfKstDay } from '@/lib/time'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import { colorOf, DAY_END, DAY_START, HOURS, PX_PER_MIN } from './grid'

const props = defineProps<{
  weekStart: Date
  interviewers: Interviewer[]
  selected: string[]
  availabilities: Availability[]
  minCount: number
  highlight: ScheduleSuggestion | null
  editFor: string | null
}>()
const emit = defineEmits<{ cellClick: [start: Date]; blockClick: [a: Availability] }>()

const now = useNow(60_000)
const height = (DAY_END - DAY_START) * PX_PER_MIN
const top = (date: Date | string) => (kstMinuteOfDay(date) - DAY_START) * PX_PER_MIN

const by = computed(() => availabilityByInterviewer(props.availabilities))
const common = computed(() => commonFreeIntervals(by.value, props.selected, props.minCount))
const lanes = computed(() =>
  props.selected
    .map((id) => props.interviewers.findIndex((i) => i.id === id))
    .filter((i) => i >= 0)
    .map((idx) => ({ idx, iv: props.interviewers[idx]! })),
)

function clampToDay(start: number, end: number, day: Date) {
  const s = Math.max(start, addMinutes(day, DAY_START).getTime())
  const e = Math.min(end, addMinutes(day, DAY_END).getTime())
  return e > s ? { s, e } : null
}

/** Everything one day column draws, positioned in px from DAY_START. */
const days = computed(() =>
  Array.from({ length: 5 }, (_, i) => {
    const day = addDays(props.weekStart, i)
    const dayStart = startOfKstDay(day)
    const today = isSameKstDay(day, now.value)
    const pastUntil = today
      ? Math.min(Math.max(kstMinuteOfDay(now.value) - DAY_START, 0), DAY_END - DAY_START)
      : now.value > day
        ? DAY_END - DAY_START
        : 0
    const laneBlocks = lanes.value.map(({ idx, iv }) => ({
      iv,
      idx,
      blocks: props.availabilities
        .filter((a) => a.interviewer_id === iv.id)
        .flatMap((a) => {
          const r = clampToDay(new Date(a.start_at).getTime(), new Date(a.end_at).getTime(), dayStart)
          return r ? [{ a, top: top(new Date(r.s)) + 1, h: (r.e - r.s) / 60000 }] : []
        }),
    }))
    const commons = common.value.flatMap((c) => {
      const r = clampToDay(c.start, c.end, dayStart)
      return r ? [{ top: top(new Date(r.s)), h: (r.e - r.s) / 60000 }] : []
    })
    const hl =
      props.highlight && isSameKstDay(props.highlight.start_at, day)
        ? {
            top: top(props.highlight.start_at),
            h: (new Date(props.highlight.end_at).getTime() - new Date(props.highlight.start_at).getTime()) / 60000,
          }
        : null
    const nowLine = today && kstMinuteOfDay(now.value) > DAY_START && kstMinuteOfDay(now.value) < DAY_END ? top(now.value) : null
    return { key: day.toISOString(), day, dayStart, today, pastUntil, laneBlocks, commons, hl, nowLine }
  }),
)

function onColumnClick(e: MouseEvent, dayStart: Date) {
  if (!props.editFor) return
  const y = e.clientY - (e.currentTarget as HTMLElement).getBoundingClientRect().top
  const minute = DAY_START + Math.floor(y / PX_PER_MIN / 30) * 30
  if (minute + 60 > DAY_END) return
  emit('cellClick', addMinutes(dayStart, minute))
}
</script>

<template>
  <div class="overflow-x-auto">
    <div class="min-w-[680px]">
      <div class="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] border-b">
        <div></div>
        <div v-for="d in days" :key="d.key" :class="cn('px-2 py-2 text-center text-[13px] font-medium', d.today && 'text-brand')">
          {{ formatDateShort(d.day) }}
        </div>
      </div>
      <div class="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] pt-2 pb-3">
        <div class="relative" :style="{ height: `${height}px` }">
          <span
            v-for="h in HOURS"
            :key="h"
            class="absolute right-2 -translate-y-1/2 text-[11px] text-muted-foreground tabular"
            :style="{ top: `${(h * 60 - DAY_START) * PX_PER_MIN}px` }"
            >{{ String(h).padStart(2, '0') }}:00</span
          >
        </div>
        <div
          v-for="d in days"
          :key="d.key"
          :class="cn('relative border-l', editFor && 'cursor-cell')"
          :style="{ height: `${height}px` }"
          @click="(e) => onColumnClick(e, d.dayStart)"
        >
          <div
            v-for="h in HOURS.slice(0, -1)"
            :key="h"
            class="pointer-events-none absolute inset-x-0 border-t border-[var(--chart-grid)]"
            :style="{ top: `${(h * 60 - DAY_START) * PX_PER_MIN}px` }"
          ></div>
          <div
            v-if="d.pastUntil > 0"
            class="pointer-events-none absolute inset-x-0 top-0 bg-[repeating-linear-gradient(135deg,transparent_0_6px,color-mix(in_oklch,var(--foreground)_5%,transparent)_6px_7px)]"
            :style="{ height: `${d.pastUntil}px` }"
            aria-hidden="true"
          ></div>
          <!-- Lanes: one thin column per selected interviewer -->
          <div class="absolute inset-0 flex gap-0.5 px-1.5">
            <div v-for="lane in d.laneBlocks" :key="lane.iv.id" class="relative flex-1">
              <Tooltip
                v-for="b in lane.blocks"
                :key="b.a.id"
                :content="`${lane.iv.name} ${formatTime(b.a.start_at)}–${formatTime(b.a.end_at)}${editFor === lane.iv.id ? ' · 클릭해 삭제' : ''}`"
              >
                <button
                  type="button"
                  :class="
                    cn(
                      'absolute inset-x-0 overflow-hidden rounded-[4px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      editFor === lane.iv.id ? 'cursor-pointer hover:opacity-80' : 'cursor-default',
                    )
                  "
                  :style="{ top: `${b.top}px`, height: `${b.h - 2}px`, background: `color-mix(in oklch, ${colorOf(lane.idx)} 75%, transparent)` }"
                  :aria-label="`${lane.iv.name} 가용 ${formatTime(b.a.start_at)}부터 ${formatTime(b.a.end_at)}까지`"
                  @click.stop="editFor === lane.iv.id && emit('blockClick', b.a)"
                >
                  <span v-if="b.h >= 36 && d.laneBlocks.length <= 4" class="block px-1 pt-0.5 text-[10.5px] font-semibold text-white/95">{{
                    lane.iv.name.slice(0, 1)
                  }}</span>
                </button>
              </Tooltip>
            </div>
          </div>
          <!-- Common free time across the selected panel -->
          <div
            v-for="(c, i) in d.commons"
            :key="i"
            class="pointer-events-none absolute inset-x-0.5 z-[5] rounded-md border-2 border-dashed border-ring bg-[color-mix(in_oklch,var(--ring)_14%,transparent)]"
            :style="{ top: `${c.top}px`, height: `${c.h}px` }"
            aria-hidden="true"
          ></div>
          <div
            v-if="d.hl"
            class="pointer-events-none absolute inset-x-0 z-10 rounded-md ring-2 ring-ring ring-offset-1 ring-offset-card"
            :style="{ top: `${d.hl.top}px`, height: `${d.hl.h}px` }"
          ></div>
          <div v-if="d.nowLine !== null" class="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-live" :style="{ top: `${d.nowLine}px` }">
            <span class="absolute -top-[5px] -left-[5px] size-2 rounded-full bg-live"></span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
