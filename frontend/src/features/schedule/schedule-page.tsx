import { CalendarCheck2Icon, ChevronLeftIcon, ChevronRightIcon, MousePointerClickIcon, SearchXIcon, UsersIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useAvailabilities, useAvailabilityMutations, useInterviewers, useMe, useScheduleSuggestions } from '@/api/queries'
import type { Availability, Interviewer, ScheduleSuggestion } from '@/api/types'
import { Page, PageHeader } from '@/components/common/page'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Card, CardContent, Label, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Checkbox, Segmented, SegmentedItem, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Switch } from '@/components/ui/form'
import { Tooltip } from '@/components/ui/overlay'
import { availabilityByInterviewer, commonFreeIntervals } from '@/lib/schedule'
import { addDays, addMinutes, formatDate, formatDateShort, formatDuration, formatTime, isSameKstDay, kstMinuteOfDay, startOfKstDay, startOfKstWeek } from '@/lib/time'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import { BookDialog } from './book-dialog'

const DAY_START = 9 * 60
const DAY_END = 19 * 60
const PX_PER_MIN = 1
const HOURS = Array.from({ length: (DAY_END - DAY_START) / 60 + 1 }, (_, i) => DAY_START / 60 + i)

/** Interviewer colors follow the entity (global order), slots 2.. so slot 1 (blue) stays the AI/brand color. */
const colorOf = (index: number) => `var(--series-${(index % 5) + 2})`

function top(date: Date | string) {
  return (kstMinuteOfDay(date) - DAY_START) * PX_PER_MIN
}

function clampToDay(start: number, end: number, day: Date) {
  const s = Math.max(start, addMinutes(day, DAY_START).getTime())
  const e = Math.min(end, addMinutes(day, DAY_END).getTime())
  return e > s ? { s, e } : null
}

function WeekGrid({
  weekStart,
  interviewers,
  selected,
  availabilities,
  minCount,
  highlight,
  editFor,
  onCellClick,
  onBlockClick,
}: {
  weekStart: Date
  interviewers: Interviewer[]
  selected: string[]
  availabilities: Availability[]
  minCount: number
  highlight: ScheduleSuggestion | null
  editFor: string | null
  onCellClick: (start: Date) => void
  onBlockClick: (a: Availability) => void
}) {
  const now = useNow(60_000)
  const days = Array.from({ length: 5 }, (_, i) => addDays(weekStart, i))
  const by = useMemo(() => availabilityByInterviewer(availabilities), [availabilities])
  const common = useMemo(() => commonFreeIntervals(by, selected, minCount), [by, selected, minCount])
  const lanes = selected.map((id) => interviewers.findIndex((i) => i.id === id)).filter((i) => i >= 0)
  const height = (DAY_END - DAY_START) * PX_PER_MIN

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[680px]">
        <div className="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] border-b">
          <div />
          {days.map((d) => (
            <div key={d.toISOString()} className={cn('px-2 py-2 text-center text-[13px] font-medium', isSameKstDay(d, now) && 'text-brand')}>
              {formatDateShort(d)}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] pt-2 pb-3">
          <div className="relative" style={{ height }}>
            {HOURS.map((h) => (
              <span key={h} className="absolute right-2 -translate-y-1/2 text-[11px] text-muted-foreground tabular" style={{ top: (h * 60 - DAY_START) * PX_PER_MIN }}>
                {String(h).padStart(2, '0')}:00
              </span>
            ))}
          </div>
          {days.map((day) => {
            const dayStart = startOfKstDay(day)
            const pastUntil = isSameKstDay(day, now) ? Math.min(Math.max(kstMinuteOfDay(now) - DAY_START, 0), DAY_END - DAY_START) : now > day ? DAY_END - DAY_START : 0
            return (
              <div
                key={day.toISOString()}
                className={cn('relative border-l', editFor && 'cursor-cell')}
                style={{ height }}
                onClick={(e) => {
                  if (!editFor) return
                  const y = e.clientY - e.currentTarget.getBoundingClientRect().top
                  const minute = DAY_START + Math.floor(y / PX_PER_MIN / 30) * 30
                  if (minute + 60 > DAY_END) return
                  onCellClick(addMinutes(dayStart, minute))
                }}
              >
                {HOURS.slice(0, -1).map((h) => (
                  <div key={h} className="pointer-events-none absolute inset-x-0 border-t border-[var(--chart-grid)]" style={{ top: (h * 60 - DAY_START) * PX_PER_MIN }} />
                ))}
                {pastUntil > 0 && (
                  <div
                    className="pointer-events-none absolute inset-x-0 top-0 bg-[repeating-linear-gradient(135deg,transparent_0_6px,color-mix(in_oklch,var(--foreground)_5%,transparent)_6px_7px)]"
                    style={{ height: pastUntil }}
                    aria-hidden
                  />
                )}
                {/* Lanes: one thin column per selected interviewer */}
                <div className="absolute inset-0 flex gap-0.5 px-1.5">
                  {lanes.map((idx) => {
                    const iv = interviewers[idx]!
                    const blocks = availabilities.filter((a) => a.interviewer_id === iv.id)
                    return (
                      <div key={iv.id} className="relative flex-1">
                        {blocks.map((a) => {
                          const r = clampToDay(new Date(a.start_at).getTime(), new Date(a.end_at).getTime(), dayStart)
                          if (!r) return null
                          const h = (r.e - r.s) / 60000
                          const editable = editFor === iv.id
                          return (
                            <Tooltip key={a.id} content={`${iv.name} ${formatTime(a.start_at)}–${formatTime(a.end_at)}${editable ? ' · 클릭해 삭제' : ''}`}>
                              <button
                                type="button"
                                className={cn(
                                  'absolute inset-x-0 overflow-hidden rounded-[4px] text-left outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                  editable ? 'cursor-pointer hover:opacity-80' : 'cursor-default',
                                )}
                                style={{ top: top(new Date(r.s)) + 1, height: h - 2, background: `color-mix(in oklch, ${colorOf(idx)} 75%, transparent)` }}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (editable) onBlockClick(a)
                                }}
                                aria-label={`${iv.name} 가용 ${formatTime(a.start_at)}부터 ${formatTime(a.end_at)}까지`}
                              >
                                {h >= 36 && lanes.length <= 4 && <span className="block px-1 pt-0.5 text-[10.5px] font-semibold text-white/95">{iv.name.slice(0, 1)}</span>}
                              </button>
                            </Tooltip>
                          )
                        })}
                      </div>
                    )
                  })}
                </div>
                {/* Common free time across the selected panel */}
                {common.map((c, i) => {
                  const r = clampToDay(c.start, c.end, dayStart)
                  if (!r) return null
                  return (
                    <div
                      key={i}
                      className="pointer-events-none absolute inset-x-0.5 z-[5] rounded-md border-2 border-dashed border-ring bg-[color-mix(in_oklch,var(--ring)_14%,transparent)]"
                      style={{ top: top(new Date(r.s)), height: (r.e - r.s) / 60000 }}
                      aria-hidden
                    />
                  )
                })}
                {highlight && isSameKstDay(highlight.start_at, day) && (
                  <div
                    className="pointer-events-none absolute inset-x-0 z-10 rounded-md ring-2 ring-ring ring-offset-1 ring-offset-card"
                    style={{ top: top(highlight.start_at), height: (new Date(highlight.end_at).getTime() - new Date(highlight.start_at).getTime()) / 60000 }}
                  />
                )}
                {isSameKstDay(day, now) && kstMinuteOfDay(now) > DAY_START && kstMinuteOfDay(now) < DAY_END && (
                  <div className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-live" style={{ top: top(now) }}>
                    <span className="absolute -top-[5px] -left-[5px] size-2 rounded-full bg-live" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function SchedulePage() {
  const interviewers = useInterviewers()
  const me = useMe()
  const [weekOffset, setWeekOffset] = useState(0)
  const [family, setFamily] = useState<string>('공정개발')
  const [picked, setPicked] = useState<string[] | null>(null)
  const [duration, setDuration] = useState(60)
  const [minSel, setMinSel] = useState<number | null>(null)
  const [highlight, setHighlight] = useState<ScheduleSuggestion | null>(null)
  const [booking, setBooking] = useState<ScheduleSuggestion | null>(null)
  const [editMine, setEditMine] = useState(false)
  const { create, remove } = useAvailabilityMutations()

  const weekStart = useMemo(() => addDays(startOfKstWeek(new Date()), weekOffset * 7), [weekOffset])
  const from = weekStart.toISOString()
  const to = addDays(weekStart, 5).toISOString()
  const avail = useAvailabilities(from, to)

  const all = interviewers.data ?? []
  const families = [...new Set(all.map((i) => i.job_family ?? '기타'))]
  const shown = family === '전체' ? all : all.filter((i) => i.job_family === family)
  const selected = picked ?? shown.filter((i) => i.job_family === family).map((i) => i.id)
  const minCount = Math.min(minSel ?? selected.length, selected.length)
  const suggestions = useScheduleSuggestions({
    interviewer_ids: selected,
    from,
    to: addDays(weekStart, 12).toISOString(),
    duration_minutes: duration,
    min_interviewers: minCount,
  })
  const focus = (s: ScheduleSuggestion | null) => {
    setHighlight(s)
    if (s) setWeekOffset(Math.round((startOfKstWeek(s.start_at).getTime() - startOfKstWeek(new Date()).getTime()) / (7 * 86_400_000)))
  }

  const toggle = (id: string) => {
    setPicked(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])
    setHighlight(null)
  }

  const onCellClick = (start: Date) => {
    if (!me.data) return
    create.mutate(
      { interviewer_id: me.data.id, start_at: start.toISOString(), end_at: addMinutes(start, 60).toISOString() },
      { onError: (e) => toast.error('가용 시간을 추가하지 못했습니다', { description: e instanceof ApiError ? e.message : undefined }) },
    )
  }

  if (interviewers.isError) return <Page><ErrorState error={interviewers.error} onRetry={() => void interviewers.refetch()} /></Page>

  return (
    <Page>
      <PageHeader
        eyebrow="FR-09"
        title="면접관 스케줄"
        description="면접관 가용 시간(수기 입력)을 겹쳐 보고, 선택한 패널이 함께 비는 시간을 찾아 일정을 잡습니다."
      />
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardContent className="space-y-3 pt-4">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
                  <UsersIcon className="size-4 text-muted-foreground" aria-hidden />
                  면접관
                </h2>
                <span className="text-xs text-muted-foreground tabular">{selected.length}명 선택</span>
              </div>
              <Select value={family} onValueChange={(v) => (setFamily(v), setPicked(null), setHighlight(null))}>
                <SelectTrigger className="h-8 text-[13px]" aria-label="직군">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="전체">전체 직군</SelectItem>
                  {families.map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {interviewers.isPending ? (
                <Skeleton className="h-32" />
              ) : (
                <ul className="space-y-1">
                  {shown.map((iv) => {
                    const idx = all.findIndex((x) => x.id === iv.id)
                    return (
                      <li key={iv.id}>
                        <label className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-subtle">
                          <Checkbox checked={selected.includes(iv.id)} onCheckedChange={() => toggle(iv.id)} aria-label={`${iv.name} 선택`} />
                          <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: colorOf(idx) }} aria-hidden />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[13px] font-medium">
                              {iv.name}
                              {iv.id === me.data?.id && <span className="ml-1 text-xs font-normal text-muted-foreground">(나)</span>}
                            </span>
                            <span className="block truncate text-[11.5px] text-muted-foreground">{iv.department}</span>
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-4 pt-4">
              <h2 className="text-[13px] font-semibold">조건</h2>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">면접 길이</Label>
                <Segmented type="single" value={String(duration)} onValueChange={(v) => v && setDuration(Number(v))} aria-label="면접 길이">
                  {[60, 90, 120].map((m) => (
                    <SegmentedItem key={m} value={String(m)}>
                      {formatDuration(m)}
                    </SegmentedItem>
                  ))}
                </Segmented>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">최소 인원</Label>
                <Select value={String(minCount)} onValueChange={(v) => setMinSel(Number(v))} disabled={selected.length === 0}>
                  <SelectTrigger className="h-8 text-[13px]" aria-label="최소 인원">
                    <SelectValue placeholder="면접관을 선택하세요" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: selected.length }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n === selected.length ? `선택한 ${n}명 모두` : `${n}명 이상`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-2 pt-4">
              <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
                <CalendarCheck2Icon className="size-4 text-muted-foreground" aria-hidden />
                후보 시간
              </h2>
              {selected.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">면접관을 선택하세요.</p>
              ) : suggestions.isPending ? (
                <Skeleton className="h-24" />
              ) : suggestions.data && suggestions.data.length > 0 ? (
                <ul className="space-y-1.5">
                  {suggestions.data.map((s) => {
                    const active = highlight?.start_at === s.start_at
                    return (
                      <li key={s.start_at + s.interviewer_ids.join()}>
                        <div
                          className={cn(
                            'flex items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors',
                            active ? 'border-ring bg-brand-soft' : 'hover:bg-subtle',
                          )}
                        >
                          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => focus(active ? null : s)}>
                            <span className="block text-[13px] font-medium tabular">
                              {formatDate(s.start_at)} {formatTime(s.start_at)}–{formatTime(s.end_at)}
                            </span>
                            <span className="block truncate text-[11.5px] text-muted-foreground">
                              {s.interviewer_ids.map((id) => all.find((i) => i.id === id)?.name).join(', ')}
                            </span>
                          </button>
                          <Button size="xs" variant={active ? 'default' : 'outline'} onClick={() => (focus(s), setBooking(s))}>
                            면접 잡기
                          </Button>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <EmptyState compact icon={SearchXIcon} title="함께 비는 시간이 없습니다" description="최소 인원을 낮추거나 다른 주를 보세요." />
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="min-w-0">
          <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon-sm" onClick={() => setWeekOffset((w) => w - 1)} aria-label="이전 주">
                <ChevronLeftIcon />
              </Button>
              <Button variant="outline" size="sm" onClick={() => setWeekOffset(0)} disabled={weekOffset === 0}>
                이번 주
              </Button>
              <Button variant="ghost" size="icon-sm" onClick={() => setWeekOffset((w) => w + 1)} aria-label="다음 주">
                <ChevronRightIcon />
              </Button>
            </div>
            <span className="text-sm font-medium tabular">
              {formatDate(weekStart)} – {formatDate(addDays(weekStart, 4))}
            </span>
            <div className="ml-auto flex items-center gap-4">
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="size-3 rounded-[3px] border-2 border-dashed border-ring bg-[color-mix(in_oklch,var(--ring)_14%,transparent)]" aria-hidden />
                공통 빈 시간
              </span>
              <div className="flex items-center gap-2">
                <Switch id="edit-mine" checked={editMine} onCheckedChange={setEditMine} disabled={!me.data || !selected.includes(me.data.id)} />
                <Label htmlFor="edit-mine" className="text-xs font-normal text-muted-foreground">
                  내 가용 시간 편집
                </Label>
              </div>
            </div>
          </div>
          {editMine && (
            <p className="flex items-center gap-1.5 border-b bg-subtle px-4 py-2 text-xs text-muted-foreground">
              <MousePointerClickIcon className="size-3.5" aria-hidden />빈 칸을 누르면 1시간이 추가되고, 내 블록을 누르면 삭제됩니다. 캘린더 연동은 Phase 2입니다.
            </p>
          )}
          <div className="p-3">
            {avail.isError ? (
              <ErrorState error={avail.error} onRetry={() => void avail.refetch()} />
            ) : avail.isPending || interviewers.isPending ? (
              <Skeleton className="h-[620px]" />
            ) : (
              <WeekGrid
                weekStart={weekStart}
                interviewers={all}
                selected={selected}
                availabilities={avail.data}
                minCount={minCount}
                highlight={highlight}
                editFor={editMine ? (me.data?.id ?? null) : null}
                onCellClick={onCellClick}
                onBlockClick={(a) => remove.mutate(a.id)}
              />
            )}
          </div>
        </Card>
      </div>
      <BookDialog key={booking?.start_at ?? 'closed'} slot={booking} interviewers={all} onClose={() => setBooking(null)} />
    </Page>
  )
}
