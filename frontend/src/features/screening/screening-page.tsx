import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon, FileSearchIcon, SearchIcon, SearchXIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router'

import { useApplications, usePostings } from '@/api/queries'
import type { ApplicationRow } from '@/api/types'
import { Pseudonym, PrivacyNote } from '@/components/common/deid'
import { Page, PageHeader } from '@/components/common/page'
import { FitBar } from '@/components/common/score'
import { ScreeningBadge, StageBadge } from '@/components/common/status'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Card, Input, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/form'
import { SCREENING_STATUS_LABEL } from '@/lib/labels'
import { formatDateShort } from '@/lib/time'
import { cn } from '@/lib/utils'

import { ApplicationSheet } from './application-sheet'
import { countByStatus, filterRows, sortRows, type Sort, type SortKey, type StatusFilter } from './table-logic'

const FILTERS: StatusFilter[] = ['all', 'passed', 'hold', 'rejected']

function SortHeader({ label, k, sort, onSort, className }: { label: string; k: SortKey; sort: Sort; onSort: (k: SortKey) => void; className?: string }) {
  const active = sort.key === k
  const Icon = !active ? ChevronsUpDownIcon : sort.dir === 'asc' ? ArrowUpIcon : ArrowDownIcon
  return (
    <th className={cn('px-3 py-2.5 font-medium', className)} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(k)} className={cn('inline-flex items-center gap-1 hover:text-foreground', active && 'text-foreground')}>
        {label}
        <Icon className="size-3.5" aria-hidden />
      </button>
    </th>
  )
}

export function ScreeningTable({ rows, onOpen, selectedId }: { rows: ApplicationRow[]; onOpen: (id: string) => void; selectedId: string | null }) {
  const [status, setStatus] = useState<StatusFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>({ key: 'fit', dir: 'desc' })
  const counts = useMemo(() => countByStatus(rows), [rows])
  const visible = useMemo(() => sortRows(filterRows(rows, status, query), sort), [rows, status, query, sort])
  const onSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'pseudonym' ? 'asc' : 'desc' }))

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <Segmented type="single" value={status} onValueChange={(v) => v && setStatus(v as StatusFilter)} aria-label="선별 상태 필터">
          {FILTERS.map((f) => (
            <SegmentedItem key={f} value={f}>
              {f === 'all' ? '전체' : SCREENING_STATUS_LABEL[f]}
              <span className="text-[11.5px] text-muted-foreground tabular">{counts[f]}</span>
            </SegmentedItem>
          ))}
        </Segmented>
        <div className="relative ml-auto w-full max-w-64">
          <SearchIcon className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="가명 또는 기술 검색" className="h-8 pl-8 text-[13px]" aria-label="지원자 검색" />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[13px]">
          <thead>
            <tr className="border-b bg-subtle text-left text-xs text-muted-foreground">
              <SortHeader label="지원자" k="pseudonym" sort={sort} onSort={onSort} className="pl-4" />
              <SortHeader label="적합도" k="fit" sort={sort} onSort={onSort} />
              <th className="px-3 py-2.5 font-medium">상태</th>
              <SortHeader label="경력" k="years" sort={sort} onSort={onSort} />
              <th className="px-3 py-2.5 font-medium">핵심 기술</th>
              <th className="px-3 py-2.5 font-medium">진행</th>
              <SortHeader label="접수" k="created" sort={sort} onSort={onSort} className="pr-4" />
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.application_id}
                onClick={() => onOpen(r.application_id)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen(r.application_id))}
                tabIndex={0}
                aria-selected={selectedId === r.application_id}
                className={cn(
                  'cursor-pointer border-b transition-colors outline-none last:border-0 hover:bg-subtle focus-visible:bg-accent',
                  selectedId === r.application_id && 'bg-accent',
                )}
                data-testid="screening-row"
              >
                <td className="py-3 pr-3 pl-4">
                  <Pseudonym value={r.candidate.pseudonym} size="sm" />
                </td>
                <td className="px-3 py-3">{r.screening ? <FitBar value={r.screening.fit_score} /> : <span className="text-muted-foreground">선별 전</span>}</td>
                <td className="px-3 py-3">{r.screening && <ScreeningBadge status={r.screening.status} />}</td>
                <td className="px-3 py-3 tabular">{r.years_experience != null ? `${r.years_experience}년` : '–'}</td>
                <td className="px-3 py-3">
                  <div className="flex max-w-64 flex-wrap gap-1">
                    {r.top_skills.map((s) => (
                      <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">
                        {s}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <StageBadge stage={r.stage} />
                </td>
                <td className="py-3 pr-4 pl-3 text-muted-foreground tabular">{formatDateShort(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <EmptyState
            compact
            icon={SearchXIcon}
            title="조건에 맞는 지원자가 없습니다"
            action={
              <Button size="sm" variant="outline" onClick={() => (setStatus('all'), setQuery(''))}>
                필터 초기화
              </Button>
            }
          />
        )}
      </div>
    </Card>
  )
}

export default function ScreeningPage() {
  const { postingId } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const postings = usePostings()
  const apps = useApplications(postingId)
  const selected = params.get('app')

  if (!postingId) {
    if (postings.isError) return <Page><ErrorState error={postings.error} onRetry={() => void postings.refetch()} /></Page>
    const first = postings.data?.find((p) => p.counts.applications > 0) ?? postings.data?.[0]
    if (first) return <Navigate to={`/screening/${first.id}`} replace />
    return <Page><Skeleton className="h-96" /></Page>
  }

  const posting = postings.data?.find((p) => p.id === postingId)
  const open = (id: string) => setParams((p) => (p.set('app', id), p), { replace: true })
  const close = () => setParams((p) => (p.delete('app'), p), { replace: true })

  return (
    <Page>
      <PageHeader
        eyebrow="FR-01 · FR-03"
        title="서류 선별"
        description="JD와 확정된 역량 사전 기준의 AI 적합도와 근거입니다. 통과·보류·탈락은 사람이 확정합니다."
        actions={
          <Select value={postingId} onValueChange={(v) => navigate(`/screening/${v}`)}>
            <SelectTrigger className="w-80" aria-label="공고 선택">
              <SelectValue placeholder="공고 선택" />
            </SelectTrigger>
            <SelectContent>
              {postings.data?.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.title} · {p.counts.applications}명
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      {apps.isError ? (
        <ErrorState error={apps.error} onRetry={() => void apps.refetch()} />
      ) : apps.isPending ? (
        <Card className="space-y-3 p-4">
          <Skeleton className="h-8 w-80" />
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </Card>
      ) : apps.data.length === 0 ? (
        <Card>
          <EmptyState
            icon={FileSearchIcon}
            title="아직 지원서가 없습니다"
            description={posting?.status === 'draft' ? '공고가 작성 중입니다. 역량 사전을 확정하고 공고를 열면 서류 선별이 시작됩니다.' : '지원서가 들어오면 AI가 적합도와 근거를 붙여 이곳에 보여 줍니다.'}
          />
        </Card>
      ) : (
        <ScreeningTable rows={apps.data} onOpen={open} selectedId={selected} />
      )}
      <PrivacyNote className="mt-3" />
      <ApplicationSheet applicationId={selected} postingId={postingId} onClose={close} />
    </Page>
  )
}
