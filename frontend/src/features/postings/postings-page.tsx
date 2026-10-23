import { ArrowUpRightIcon, BookCheckIcon, BriefcaseBusinessIcon, FilePenLineIcon } from 'lucide-react'
import { Link } from 'react-router'

import { usePostings } from '@/api/queries'
import type { PostingStatus, PostingSummary } from '@/api/types'
import { FadeIn } from '@/components/common/motion'
import { Page, PageHeader } from '@/components/common/page'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Badge, Card, Skeleton } from '@/components/ui/basic'
import { POSTING_STATUS_LABEL } from '@/lib/labels'
import { formatFullDate } from '@/lib/time'

const statusVariant: Record<PostingStatus, 'success' | 'outline' | 'secondary'> = { open: 'success', draft: 'outline', closed: 'secondary' }

function CompetencyState({ p }: { p: PostingSummary }) {
  const latest = p.latest_competency_set
  const approved = p.approved_competency_set
  if (!latest) return <span className="text-muted-foreground">역량 사전 없음</span>
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {approved ? (
        <span className="inline-flex items-center gap-1 text-success">
          <BookCheckIcon className="size-3.5" aria-hidden />v{approved.version} 확정
        </span>
      ) : (
        <span className="text-warning">확정본 없음</span>
      )}
      {latest.approved_at === null && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <FilePenLineIcon className="size-3.5" aria-hidden />v{latest.version} 초안 검토 중
        </span>
      )}
    </span>
  )
}

export default function PostingsPage() {
  const q = usePostings()
  return (
    <Page>
      <PageHeader eyebrow="FR-02" title="공고·역량 사전" description="공고마다 JD 원문과 역량 사전(1~5점 BARS)을 버전으로 관리합니다. 확정된 버전이 선별과 평가 기준이 됩니다." />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-48 rounded-xl" />
          ))}
        </div>
      ) : q.data.length === 0 ? (
        <EmptyState icon={BriefcaseBusinessIcon} title="등록된 공고가 없습니다" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data.map((p, i) => (
            <FadeIn key={p.id} delay={i * 0.04}>
              <Link to={`/postings/${p.id}`} className="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                <Card className="flex h-full flex-col p-5 transition-colors group-hover:border-foreground/15">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs text-muted-foreground">{p.job_family}</p>
                      <h2 className="mt-1 text-[15px] leading-snug font-semibold">{p.title}</h2>
                    </div>
                    <ArrowUpRightIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden />
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <Badge variant={statusVariant[p.status]}>{POSTING_STATUS_LABEL[p.status]}</Badge>
                    <span className="text-xs text-muted-foreground">{formatFullDate(p.created_at)} 등록</span>
                  </div>
                  <dl className="mt-5 grid grid-cols-4 gap-2 border-t pt-4">
                    {(
                      [
                        ['지원', p.counts.applications],
                        ['통과', p.counts.passed],
                        ['면접', p.counts.interviewing + p.counts.interviewed],
                        ['평가 완료', p.counts.evaluated],
                      ] as const
                    ).map(([label, v]) => (
                      <div key={label}>
                        <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
                        <dd className="text-lg font-semibold tabular">{v}</dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-auto pt-4 text-xs">
                    <CompetencyState p={p} />
                  </div>
                </Card>
              </Link>
            </FadeIn>
          ))}
        </div>
      )}
    </Page>
  )
}
