import {
  ArrowRightIcon,
  BriefcaseBusinessIcon,
  CalendarClockIcon,
  CalendarOffIcon,
  ClipboardListIcon,
  HistoryIcon,
  InboxIcon,
  MicIcon,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'

import { useActivity, useDashboard, useMe } from '@/api/queries'
import type { PipelineRow, SessionSummary } from '@/api/types'
import { Pseudonym } from '@/components/common/deid'
import { FadeIn } from '@/components/common/motion'
import { Page, PageHeader } from '@/components/common/page'
import { PanelAvatars } from '@/components/common/people'
import { AiScoringBadge, ModeBadge, SessionStatusBadge } from '@/components/common/status'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { POSTING_STATUS_LABEL } from '@/lib/labels'
import { formatDate, formatRelative, formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

import { ActivityFeed } from './activity-feed'

function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  to,
  live,
  delay,
}: {
  label: string
  value: number | string
  hint: string
  icon: LucideIcon
  to?: string
  live?: boolean
  delay: number
}) {
  const body = (
    <Card className={cn('group h-full px-4 py-3.5 transition-colors', to && 'hover:border-foreground/15')}>
      <div className="flex items-center justify-between">
        <span className="text-[13px] text-muted-foreground">{label}</span>
        <Icon className="size-4 text-muted-foreground/70" aria-hidden />
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-[28px] leading-none font-semibold tracking-tight">{value}</span>
        {live && <span className="size-2 animate-live rounded-full bg-live" aria-label="진행 중" />}
      </div>
      <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>
    </Card>
  )
  return (
    <FadeIn delay={delay}>
      {to ? (
        <Link to={to} className="block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          {body}
        </Link>
      ) : (
        body
      )}
    </FadeIn>
  )
}

const STAGES = [
  { key: 'applications', label: '지원', color: 'var(--funnel-1)' },
  { key: 'passed', label: '서류 통과', color: 'var(--funnel-2)' },
  { key: 'interview', label: '면접', color: 'var(--funnel-3)' },
  { key: 'evaluated', label: '평가 완료', color: 'var(--funnel-4)' },
] as const

function stageValue(row: PipelineRow, key: (typeof STAGES)[number]['key']) {
  const c = row.counts
  if (key === 'interview') return c.interviewing + c.interviewed
  return c[key]
}

function PipelineRowView({ row }: { row: PipelineRow }) {
  const total = Math.max(1, row.counts.applications)
  return (
    <div className="grid grid-cols-1 gap-3 py-4 first:pt-1 last:pb-1 md:grid-cols-[minmax(0,220px)_1fr] md:gap-6">
      <div className="min-w-0">
        <Link to={`/postings/${row.posting.id}`} className="block truncate text-sm font-medium hover:underline">
          {row.posting.title}
        </Link>
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span>{row.posting.job_family}</span>
          <span aria-hidden>·</span>
          <span>{POSTING_STATUS_LABEL[row.posting.status]}</span>
        </div>
      </div>
      {row.counts.applications === 0 ? (
        <div className="flex items-center text-[13px] text-muted-foreground">아직 지원자가 없습니다. 공고를 열면 서류 선별이 시작됩니다.</div>
      ) : (
        <div className="grid grid-cols-4 gap-3">
          {STAGES.map((s, i) => {
            const v = stageValue(row, s.key)
            return (
              <div key={s.key} className="min-w-0">
                <div className="flex items-baseline justify-between gap-1">
                  <span className="truncate text-xs text-muted-foreground">{s.label}</span>
                  {i > 0 && <span className="text-[11px] text-muted-foreground/80 tabular">{Math.round((v / total) * 100)}%</span>}
                </div>
                <div className="mt-1 text-lg leading-none font-semibold tabular">{v}</div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${(v / total) * 100}%`, background: s.color }} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function SessionLine({ s }: { s: SessionSummary }) {
  const to = s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`
  return (
    <li>
      <Link
        to={to}
        className={cn(
          'flex items-center gap-3 rounded-lg border border-transparent px-2.5 py-2.5 transition-colors hover:border-border hover:bg-subtle',
          s.status === 'in_progress' && 'border-[color-mix(in_oklch,var(--live)_30%,transparent)] bg-[color-mix(in_oklch,var(--live)_6%,transparent)]',
        )}
      >
        <div className="w-12 shrink-0 text-center">
          <div className="text-sm font-semibold tabular">{s.scheduled_at ? formatTime(s.scheduled_at) : '–'}</div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Pseudonym value={s.candidate.pseudonym} size="sm" />
            <SessionStatusBadge status={s.status} />
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            <span className="truncate">{s.posting.title}</span>
            <ModeBadge mode={s.mode} />
          </div>
        </div>
        <PanelAvatars panel={s.interviewers} />
        <ArrowRightIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </Link>
    </li>
  )
}

export default function DashboardPage() {
  const me = useMe()
  const dash = useDashboard()
  const activity = useActivity(14)
  const today = new Date()

  if (dash.isError) {
    return (
      <Page>
        <ErrorState error={dash.error} onRetry={() => void dash.refetch()} />
      </Page>
    )
  }

  const d = dash.data
  const live = d?.today_sessions.find((s) => s.status === 'in_progress')
  const upcoming = d?.today_sessions.filter((s) => s.status === 'scheduled').length ?? 0
  const openPostings = d?.pipeline.filter((p) => p.posting.status === 'open').length ?? 0
  const applications = d?.pipeline.reduce((sum, p) => sum + p.counts.applications, 0) ?? 0

  return (
    <Page>
      <PageHeader
        eyebrow={formatDate(today)}
        title={me.data ? `안녕하세요, ${me.data.name}님` : '대시보드'}
        description="공고별 진행 현황과 오늘 면접, 최근 활동을 한눈에 봅니다."
        actions={
          live && (
            <Button asChild>
              <Link to={`/sessions/${live.id}/live`}>
                <MicIcon />
                진행 중 면접으로
              </Link>
            </Button>
          )
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {d ? (
          <>
            <StatTile delay={0} label="진행 중 공고" value={openPostings} hint={`지원서 ${applications}건`} icon={BriefcaseBusinessIcon} to="/postings" />
            <StatTile
              delay={0.04}
              label="오늘 면접"
              value={d.today_sessions.length}
              hint={live ? `1건 진행 중 · ${upcoming}건 예정` : `${upcoming}건 예정`}
              icon={CalendarClockIcon}
              to="/sessions"
              live={Boolean(live)}
            />
            <StatTile
              delay={0.08}
              label="내 평가 대기"
              value={d.pending_my_scores.length}
              hint={d.pending_my_scores.length > 0 ? '점수를 입력해야 평가가 마무리됩니다' : '모두 제출했습니다'}
              icon={ClipboardListIcon}
              to={d.pending_my_scores[0] ? `/sessions/${d.pending_my_scores[0].id}/evaluation` : undefined}
            />
            <StatTile delay={0.12} label="서류 보류" value={d.hold_count} hint="사람의 검토가 필요한 지원서" icon={InboxIcon} to="/screening" />
          </>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[108px] rounded-xl" />)
        )}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-4">
          <FadeIn delay={0.1}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>공고별 진행 현황</CardTitle>
                  <CardDescription>서류 → 면접 → 평가 단계별 인원</CardDescription>
                </div>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/screening">
                    서류 선별
                    <ArrowRightIcon />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent className="divide-y">
                {d ? (
                  d.pipeline.map((row) => <PipelineRowView key={row.posting.id} row={row} />)
                ) : (
                  <div className="space-y-4 py-2">
                    {Array.from({ length: 3 }, (_, i) => (
                      <Skeleton key={i} className="h-14" />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.16}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>최근 활동</CardTitle>
                  <CardDescription>감사 로그에서 사람이 볼 만한 항목만 보여 줍니다</CardDescription>
                </div>
                <HistoryIcon className="size-4 text-muted-foreground" aria-hidden />
              </CardHeader>
              <CardContent>
                {activity.isError ? (
                  <ErrorState error={activity.error} onRetry={() => void activity.refetch()} className="py-6" />
                ) : activity.data ? (
                  activity.data.length > 0 ? (
                    <ActivityFeed items={activity.data} />
                  ) : (
                    <EmptyState compact icon={HistoryIcon} title="아직 활동이 없습니다" />
                  )
                ) : (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }, (_, i) => (
                      <div key={i} className="flex gap-3">
                        <Skeleton className="size-7 rounded-full" />
                        <div className="flex-1 space-y-1.5 pt-1">
                          <Skeleton className="h-3.5 w-4/5" />
                          <Skeleton className="h-3 w-16" />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </FadeIn>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <FadeIn delay={0.12}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>오늘 면접</CardTitle>
                  <CardDescription>{formatDate(today)}</CardDescription>
                </div>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/sessions">
                    전체
                    <ArrowRightIcon />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent className="px-3">
                {d ? (
                  d.today_sessions.length > 0 ? (
                    <ul className="space-y-1">
                      {d.today_sessions.map((s) => (
                        <SessionLine key={s.id} s={s} />
                      ))}
                    </ul>
                  ) : (
                    <EmptyState
                      compact
                      icon={CalendarOffIcon}
                      title="오늘 잡힌 면접이 없습니다"
                      action={
                        <Button asChild size="sm" variant="outline">
                          <Link to="/schedule">일정 잡기</Link>
                        </Button>
                      }
                    />
                  )
                ) : (
                  <div className="space-y-2 px-2">
                    {Array.from({ length: 3 }, (_, i) => (
                      <Skeleton key={i} className="h-14" />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.18}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>내 평가 대기</CardTitle>
                  <CardDescription>면접관 점수는 AI 점수와 따로 저장됩니다</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="px-3">
                {d ? (
                  d.pending_my_scores.length > 0 ? (
                    <ul className="space-y-1">
                      {d.pending_my_scores.map((s) => (
                        <li key={s.id}>
                          <Link
                            to={`/sessions/${s.id}/evaluation`}
                            className="flex items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-subtle"
                          >
                            <div className="min-w-0 flex-1">
                              <Pseudonym value={s.candidate.pseudonym} size="sm" />
                              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                                {s.posting.title} · {s.ended_at ? formatRelative(s.ended_at) : ''} 종료
                              </div>
                            </div>
                            <AiScoringBadge status={s.ai_scoring} />
                            <Badge variant="warning">입력 필요</Badge>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState compact icon={ClipboardListIcon} title="제출할 평가가 없습니다" />
                  )
                ) : (
                  <Skeleton className="mx-2 h-14" />
                )}
              </CardContent>
            </Card>
          </FadeIn>
        </div>
      </div>
    </Page>
  )
}
