import { ArrowRightIcon, CalendarPlusIcon, MicIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { useMe, useSessions } from '@/api/queries'
import type { SessionStatus, SessionSummary } from '@/api/types'
import { Pseudonym } from '@/components/common/deid'
import { Page, PageHeader } from '@/components/common/page'
import { PanelAvatars } from '@/components/common/people'
import { AiScoringBadge, ModeBadge, SessionStatusBadge } from '@/components/common/status'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Badge, Card, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem } from '@/components/ui/form'
import { formatDateTime } from '@/lib/time'

type Filter = 'all' | Exclude<SessionStatus, 'cancelled'>
const FILTERS: { v: Filter; label: string }[] = [
  { v: 'all', label: '전체' },
  { v: 'in_progress', label: '진행 중' },
  { v: 'scheduled', label: '예정' },
  { v: 'completed', label: '완료' },
]

const ORDER: Record<SessionStatus, number> = { in_progress: 0, scheduled: 1, completed: 2, cancelled: 3 }

function sortSessions(list: SessionSummary[]) {
  return [...list].sort((a, b) => {
    if (ORDER[a.status] !== ORDER[b.status]) return ORDER[a.status] - ORDER[b.status]
    const x = a.scheduled_at ?? ''
    const y = b.scheduled_at ?? ''
    return a.status === 'scheduled' ? x.localeCompare(y) : y.localeCompare(x)
  })
}

function Action({ s }: { s: SessionSummary }) {
  if (s.status === 'in_progress')
    return (
      <Button asChild size="xs">
        <Link to={`/sessions/${s.id}/live`}>
          <MicIcon />
          입장
        </Link>
      </Button>
    )
  if (s.status === 'scheduled')
    return (
      <Button asChild size="xs" variant="outline">
        <Link to={`/sessions/${s.id}/live`}>준비</Link>
      </Button>
    )
  if (s.status === 'completed')
    return (
      <Button asChild size="xs" variant="outline">
        <Link to={`/sessions/${s.id}/evaluation`}>
          평가
          <ArrowRightIcon />
        </Link>
      </Button>
    )
  return null
}

export default function SessionsPage() {
  const q = useSessions()
  const me = useMe()
  const [filter, setFilter] = useState<Filter>('all')
  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, in_progress: 0, scheduled: 0, completed: 0 }
    for (const s of q.data ?? []) {
      if (s.status === 'cancelled') continue
      c.all += 1
      c[s.status] += 1
    }
    return c
  }, [q.data])
  const rows = useMemo(
    () => sortSessions((q.data ?? []).filter((s) => s.status !== 'cancelled' && (filter === 'all' || s.status === filter))),
    [q.data, filter],
  )

  return (
    <Page>
      <PageHeader
        eyebrow="FR-04 ~ FR-08"
        title="면접"
        description="면접 세션을 열어 실시간 보조를 받고, 끝난 면접은 평가 화면에서 AI 참고 점수와 면접관 점수를 따로 확인합니다."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/schedule">
              <CalendarPlusIcon />
              일정 잡기
            </Link>
          </Button>
        }
      />
      <Card className="overflow-hidden">
        <div className="border-b px-4 py-3">
          <Segmented type="single" value={filter} onValueChange={(v) => v && setFilter(v as Filter)} aria-label="상태 필터">
            {FILTERS.map((f) => (
              <SegmentedItem key={f.v} value={f.v}>
                {f.label}
                <span className="text-[11.5px] text-muted-foreground tabular">{counts[f.v]}</span>
              </SegmentedItem>
            ))}
          </Segmented>
        </div>
        {q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon={MicIcon} title="해당하는 면접이 없습니다" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-[13px]">
              <thead>
                <tr className="border-b bg-subtle text-left text-xs text-muted-foreground">
                  <th className="py-2.5 pr-3 pl-4 font-medium">일시</th>
                  <th className="px-3 py-2.5 font-medium">지원자</th>
                  <th className="px-3 py-2.5 font-medium">공고</th>
                  <th className="px-3 py-2.5 font-medium">방식</th>
                  <th className="px-3 py-2.5 font-medium">면접관</th>
                  <th className="px-3 py-2.5 font-medium">상태</th>
                  <th className="px-3 py-2.5 font-medium">평가</th>
                  <th className="py-2.5 pr-4 pl-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const mine = me.data && s.interviewers.some((i) => i.interviewer_id === me.data.id)
                  const myPending = mine && s.status === 'completed' && !s.submitted_interviewer_ids.includes(me.data!.id)
                  return (
                    <tr key={s.id} className="border-b transition-colors last:border-0 hover:bg-subtle">
                      <td className="py-3 pr-3 pl-4 tabular">{s.scheduled_at ? formatDateTime(s.scheduled_at) : '–'}</td>
                      <td className="px-3 py-3">
                        <Pseudonym value={s.candidate.pseudonym} size="sm" />
                      </td>
                      <td className="max-w-56 truncate px-3 py-3 text-muted-foreground">{s.posting.title}</td>
                      <td className="px-3 py-3">
                        <ModeBadge mode={s.mode} />
                      </td>
                      <td className="px-3 py-3">
                        <PanelAvatars panel={s.interviewers} />
                      </td>
                      <td className="px-3 py-3">
                        <SessionStatusBadge status={s.status} />
                      </td>
                      <td className="px-3 py-3">
                        {s.status === 'completed' ? (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <AiScoringBadge status={s.ai_scoring} />
                            <Badge variant="outline" className="tabular">
                              면접관 {s.submitted_interviewer_ids.length}/{s.interviewers.length}
                            </Badge>
                            {myPending && <Badge variant="warning">내 평가 필요</Badge>}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">–</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 pl-3 text-right">
                        <Action s={s} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Page>
  )
}
