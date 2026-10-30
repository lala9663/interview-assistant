<script setup lang="ts">
import { EraserIcon, Trash2Icon } from '@lucide/vue'
import { PopoverAnchor, PopoverContent, PopoverPortal, PopoverRoot } from 'reka-ui'
import { computed, onBeforeUnmount, ref } from 'vue'

import type { Availability, Interviewer, ScheduleSuggestion } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { absorbInto, availabilityByInterviewer, commonFreeIntervals } from '@/lib/schedule'
import { addDays, addMinutes, formatDateShort, formatDuration, formatTime, isSameKstDay, kstMinuteOfDay, MINUTE, startOfKstDay } from '@/lib/time'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import { colorOf, DAY_END, DAY_START, dragRange, HOURS, paintRange, PX_PER_MIN, slotAt, STEP, type DragMode, type Range } from './grid'

const props = defineProps<{
  weekStart: Date
  interviewers: Interviewer[]
  selected: string[]
  availabilities: Availability[]
  minCount: number
  highlight: ScheduleSuggestion | null
  /** The interviewer whose blocks can be edited (the signed-in one), or null when not editing. */
  editFor: string | null
}>()
const emit = defineEmits<{
  create: [start: Date, end: Date]
  update: [a: Availability, start: Date, end: Date]
  clear: [a: Availability, start: Date, end: Date]
  remove: [a: Availability]
}>()

const now = useNow(60_000)
const height = (DAY_END - DAY_START) * PX_PER_MIN
const top = (date: Date | string) => (kstMinuteOfDay(date) - DAY_START) * PX_PER_MIN
/** A block's start and end in minutes from the start of `dayStart`. */
const rangeOf = (a: Availability, dayStart: Date): Range => ({
  start: (new Date(a.start_at).getTime() - dayStart.getTime()) / MINUTE,
  end: (new Date(a.end_at).getTime() - dayStart.getTime()) / MINUTE,
})
const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`
const label = (r: Range) => `${hhmm(r.start)}–${hhmm(r.end)}`

// --- editing: one change at a time, shown merged (as the server will save it) until it is sent ---------------

interface Edit {
  /** Drag an edge or the whole block, paint a new block on empty time, or arrow keys on a block. */
  mode: DragMode | 'paint' | 'key'
  a: Availability | null
  dayStart: Date
  origin: Range
  range: Range
  y0: number
  moved: boolean
}
const edit = ref<Edit | null>(null)
const PREVIEW_ID = 'preview'
const KEY_COMMIT_MS = 700
let keyTimer: ReturnType<typeof setTimeout> | undefined

const shown = computed(() => {
  const e = edit.value
  if (!e || !e.moved || !props.editFor) return props.availabilities
  const times = { start_at: addMinutes(e.dayStart, e.range.start).toISOString(), end_at: addMinutes(e.dayStart, e.range.end).toISOString() }
  const written: Availability = e.a
    ? { ...e.a, ...times }
    : { id: PREVIEW_ID, interviewer_id: props.editFor, ...times, source: 'manual', created_at: new Date().toISOString() }
  return absorbInto(props.availabilities, written)
})
/** What the edit will save, for the floating label and screen readers. */
const editLabel = computed(() => (edit.value?.moved ? label(edit.value.range) : ''))

function commit() {
  clearTimeout(keyTimer)
  const e = edit.value
  edit.value = null
  if (!e?.moved) return
  const start = addMinutes(e.dayStart, e.range.start)
  const end = addMinutes(e.dayStart, e.range.end)
  if (!e.a) emit('create', start, end)
  else if (e.range.start !== e.origin.start || e.range.end !== e.origin.end) emit('update', e.a, start, end)
}
// Arrow-key changes waiting for their pause are kept; a drag still under the pointer is not finished, so it is dropped.
onBeforeUnmount(() => (edit.value?.mode === 'key' ? commit() : clearTimeout(keyTimer)))

function onColumnDown(ev: PointerEvent, dayStart: Date) {
  if (!props.editFor || ev.button !== 0) return
  commit()
  const at = DAY_START + (ev.clientY - (ev.currentTarget as HTMLElement).getBoundingClientRect().top) / PX_PER_MIN
  edit.value = { mode: 'paint', a: null, dayStart, origin: { start: at, end: at }, range: paintRange(at, at), y0: ev.clientY, moved: false }
  // A finger on empty time still scrolls the page; only a tap (no move) adds an hour.
  if (ev.pointerType !== 'touch') capture(ev)
}

/** Keeps the drag's events coming to this element when the pointer leaves it. Never fatal: without it the drag still works inside the column. */
function capture(ev: PointerEvent) {
  try {
    ;(ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId)
  } catch {
    // The pointer is already gone (or the event was synthetic).
  }
}

function onBlockDown(ev: PointerEvent, a: Availability, dayStart: Date) {
  ev.stopPropagation()
  if (!props.editFor || a.interviewer_id !== props.editFor || ev.button !== 0) return
  commit()
  const mode = ((ev.target as HTMLElement).dataset.edge as DragMode | undefined) ?? 'move'
  const origin = rangeOf(a, dayStart)
  edit.value = { mode, a, dayStart, origin, range: origin, y0: ev.clientY, moved: false }
  capture(ev)
}

function onPointerMove(ev: PointerEvent) {
  const e = edit.value
  if (!e || e.mode === 'key') return
  const dy = ev.clientY - e.y0
  if (!e.moved && Math.abs(dy) < 4) return
  e.moved = true
  const delta = dy / PX_PER_MIN
  e.range = e.mode === 'paint' ? paintRange(e.origin.start, Math.min(Math.max(e.origin.start + delta, DAY_START), DAY_END - 1)) : dragRange(e.origin, e.mode, delta)
}

function onPointerUp(ev: PointerEvent) {
  const e = edit.value
  if (!e || e.mode === 'key') return
  if (e.moved) return commit()
  edit.value = null
  if (e.mode === 'paint') {
    const r = paintRange(e.origin.start, e.origin.start)
    emit('create', addMinutes(e.dayStart, r.start), addMinutes(e.dayStart, r.end))
  } else if (e.a) {
    // A click on the block (the pointer is captured by it; the listener is on the day column).
    const block = (ev.target as HTMLElement).closest<HTMLElement>('[data-block]')
    const at = DAY_START + (ev.clientY - (ev.currentTarget as HTMLElement).getBoundingClientRect().top) / PX_PER_MIN
    if (block) openMenu(e.a, e.dayStart, block, at)
  }
}

function onPointerCancel() {
  if (edit.value && edit.value.mode !== 'key') edit.value = null
}

function onBlockKey(ev: KeyboardEvent, a: Availability, dayStart: Date) {
  if (!props.editFor || a.interviewer_id !== props.editFor) return
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    ev.preventDefault()
    clearTimeout(keyTimer)
    edit.value = null
    emit('remove', a)
  } else if (ev.key === 'Enter' || ev.key === ' ') {
    ev.preventDefault()
    commit()
    openMenu(a, dayStart, ev.currentTarget as HTMLElement, null)
  } else if ((ev.key === 'ArrowUp' || ev.key === 'ArrowDown') && !ev.altKey && !ev.ctrlKey && !ev.metaKey) {
    ev.preventDefault()
    const same = edit.value?.mode === 'key' && edit.value.a?.id === a.id
    const origin = same ? edit.value!.origin : rangeOf(a, dayStart)
    const from = same ? edit.value!.range : origin
    const range = dragRange(from, ev.shiftKey ? 'end' : 'move', ev.key === 'ArrowUp' ? -STEP : STEP)
    edit.value = { mode: 'key', a, dayStart, origin, range, y0: 0, moved: true }
    clearTimeout(keyTimer)
    keyTimer = setTimeout(commit, KEY_COMMIT_MS)
  }
}

function onBlockBlur(a: Availability) {
  if (edit.value?.mode === 'key' && edit.value.a?.id === a.id) commit()
}

// --- the block menu: clear the 30 minutes that were clicked, or delete the block -----------------------------

const menu = ref<{ a: Availability; dayStart: Date; slot: Range | null; rect: DOMRect } | null>(null)
const menuAnchor = computed(() => (menu.value ? { getBoundingClientRect: () => menu.value!.rect } : undefined))
const menuRange = computed(() => menu.value && rangeOf(menu.value.a, menu.value.dayStart))

/** Opens the menu beside `block`; `minute` (a click) picks the 30 minutes it offers to clear, the keyboard has none. */
function openMenu(a: Availability, dayStart: Date, block: HTMLElement, minute: number | null) {
  const r = rangeOf(a, dayStart)
  const slot = minute === null || r.end - r.start <= STEP ? null : slotAt(Math.min(Math.max(minute, r.start), r.end - 1))
  const box = block.getBoundingClientRect()
  const rect = slot
    ? new DOMRect(box.left, box.top + (slot.start - Math.max(r.start, DAY_START)) * PX_PER_MIN, box.width, STEP * PX_PER_MIN)
    : new DOMRect(box.left, box.top, box.width, box.height)
  menu.value = { a, dayStart, slot, rect }
  lastBlock = block
}
let lastBlock: HTMLElement | null = null
function menuAction(action: 'clear' | 'remove') {
  const m = menu.value
  if (!m) return
  menu.value = null
  if (action === 'remove') emit('remove', m.a)
  else if (m.slot) emit('clear', m.a, addMinutes(m.dayStart, m.slot.start), addMinutes(m.dayStart, m.slot.end))
}
/** Focus goes back to the block, unless the menu deleted it. */
function onMenuClosed(ev: Event) {
  ev.preventDefault()
  if (lastBlock?.isConnected) lastBlock.focus()
}

// --- what each day column draws ------------------------------------------------------------------------------

const by = computed(() => availabilityByInterviewer(shown.value))
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
      mine: iv.id === props.editFor,
      blocks: shown.value
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
    const editing = edit.value?.moved && edit.value.dayStart.getTime() === dayStart.getTime() ? (Math.max(edit.value.range.start, DAY_START) - DAY_START) * PX_PER_MIN : null
    return { key: day.toISOString(), day, dayStart, today, pastUntil, laneBlocks, commons, hl, nowLine, editing }
  }),
)
</script>

<template>
  <div class="overflow-x-auto">
    <div class="min-w-[680px]">
      <div class="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] border-b">
        <div class="sticky left-0 z-30 bg-card"></div>
        <div v-for="d in days" :key="d.key" :class="cn('px-2 py-2 text-center text-[13px] font-medium', d.today && 'text-brand')">
          {{ formatDateShort(d.day) }}
        </div>
      </div>
      <div class="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] pt-2 pb-3">
        <!-- Hours stay in view when a narrow screen scrolls the week sideways. -->
        <div class="sticky left-0 z-30 bg-card" :style="{ height: `${height}px` }">
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
          role="group"
          :aria-label="formatDateShort(d.day)"
          :class="cn('relative border-l', editFor && 'cursor-cell select-none')"
          :style="{ height: `${height}px` }"
          @pointerdown="(e) => onColumnDown(e, d.dayStart)"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerCancel"
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
          <!-- Lanes: one thin column per selected interviewer, side by side so no one's blocks hide another's.
               The lane being edited is wider so its edges are easy to grab. -->
          <div class="pointer-events-none absolute inset-0 flex gap-0.5 px-1.5">
            <div v-for="lane in d.laneBlocks" :key="lane.iv.id" :class="cn('@container relative', lane.mine ? 'flex-[2]' : 'flex-1')">
              <!-- Blocks being edited show their own times; a tooltip over the grid would catch the next click. -->
              <Tooltip v-for="b in lane.blocks" :key="b.a.id" :content="`${lane.iv.name} ${formatTime(b.a.start_at)}–${formatTime(b.a.end_at)}`" :disabled="lane.mine">
                <button
                  type="button"
                  data-block
                  :class="
                    cn(
                      'pointer-events-auto absolute inset-x-0 overflow-hidden rounded-[4px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-card',
                      lane.mine ? 'z-[6] cursor-grab touch-none shadow-sm active:cursor-grabbing' : 'cursor-default',
                      lane.mine && edit?.a?.id === b.a.id && 'ring-2 ring-foreground/70',
                    )
                  "
                  :style="{ top: `${b.top}px`, height: `${b.h - 2}px`, background: `color-mix(in oklch, ${colorOf(lane.idx)} ${lane.mine ? 88 : 75}%, transparent)` }"
                  :aria-label="`${lane.iv.name} 가용 ${formatTime(b.a.start_at)}부터 ${formatTime(b.a.end_at)}까지`"
                  :aria-describedby="lane.mine ? 'week-grid-edit-keys' : undefined"
                  :aria-keyshortcuts="lane.mine ? 'ArrowUp ArrowDown Shift+ArrowUp Shift+ArrowDown Delete Enter' : undefined"
                  @pointerdown="(e) => onBlockDown(e, b.a, d.dayStart)"
                  @keydown="(e) => onBlockKey(e, b.a, d.dayStart)"
                  @blur="onBlockBlur(b.a)"
                >
                  <template v-if="lane.mine">
                    <span
                      data-edge="start"
                      class="absolute inset-x-0 top-0 z-[1] flex h-2 cursor-ns-resize justify-center pt-0.5 pointer-coarse:h-3.5"
                      aria-hidden="true"
                      ><span class="pointer-events-none h-[3px] w-5 rounded-full bg-white/70"></span
                    ></span>
                    <span
                      data-edge="end"
                      class="absolute inset-x-0 bottom-0 z-[1] flex h-2 cursor-ns-resize items-end justify-center pb-0.5 pointer-coarse:h-3.5"
                      aria-hidden="true"
                      ><span class="pointer-events-none h-[3px] w-5 rounded-full bg-white/70"></span
                    ></span>
                  </template>
                  <!-- Own blocks: start–end on one line, or on two when the lane is thin. -->
                  <span
                    v-if="lane.mine && b.h >= 28"
                    class="pointer-events-none flex flex-col px-1 pt-1.5 text-[10.5px] leading-tight font-semibold text-white/95 tabular @min-[4.5rem]:flex-row"
                  >
                    <span>{{ formatTime(b.a.start_at) }}</span><span>–{{ formatTime(b.a.end_at) }}</span>
                  </span>
                  <span v-else-if="!lane.mine && b.h >= 36 && d.laneBlocks.length <= 4" class="block px-1 pt-0.5 text-[10.5px] font-semibold text-white/95">{{
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
          <!-- The time being dragged, readable however thin the lane is -->
          <div
            v-if="d.editing !== null"
            class="pointer-events-none absolute inset-x-1 z-20 flex justify-center"
            :style="{ top: `${d.editing + 2}px` }"
            aria-hidden="true"
          >
            <span class="rounded bg-foreground px-1.5 py-0.5 text-[11px] font-semibold whitespace-nowrap text-background tabular shadow">{{ editLabel }}</span>
          </div>
        </div>
      </div>
    </div>
    <p id="week-grid-edit-keys" class="sr-only">위아래 화살표로 30분씩 옮기고, Shift와 위아래 화살표로 30분씩 줄이거나 늘립니다. Delete는 삭제, Enter는 메뉴.</p>
    <p class="sr-only" aria-live="polite">{{ edit?.mode === 'key' ? editLabel : '' }}</p>

    <!-- Modal, so the click that closes it does not also add a block underneath. -->
    <PopoverRoot :open="menu !== null" modal @update:open="(open) => !open && (menu = null)">
      <PopoverAnchor v-if="menuAnchor" :reference="menuAnchor" />
      <PopoverPortal>
        <PopoverContent
          side="right"
          align="start"
          :side-offset="6"
          :collision-padding="8"
          class="z-50 w-56 rounded-lg border bg-popover p-1 text-popover-foreground shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0"
          @close-auto-focus="onMenuClosed"
        >
          <p v-if="menuRange" class="px-2 pt-1 pb-1.5 text-xs font-medium tabular">
            내 가용 {{ label(menuRange) }} <span class="font-normal text-muted-foreground">· {{ formatDuration(menuRange.end - menuRange.start) }}</span>
          </p>
          <Button v-if="menu?.slot" variant="ghost" size="sm" class="w-full justify-start" @click="menuAction('clear')">
            <EraserIcon />{{ label(menu.slot) }}만 비우기
          </Button>
          <Button variant="ghost" size="sm" class="w-full justify-start text-destructive hover:text-destructive" @click="menuAction('remove')">
            <Trash2Icon />블록 삭제
          </Button>
          <p class="border-t px-2 pt-1.5 pb-1 text-[11px] leading-relaxed text-muted-foreground">위아래 끝을 끌면 30분씩 늘이거나 줄이고, 가운데를 끌면 옮깁니다.</p>
        </PopoverContent>
      </PopoverPortal>
    </PopoverRoot>
  </div>
</template>
