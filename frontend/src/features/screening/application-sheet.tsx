import { ArrowRightIcon, BotIcon, BriefcaseIcon, CalendarIcon, FolderGit2Icon, GraduationCapIcon } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useApplication, useUpdateScreening } from '@/api/queries'
import { SCREENING_STATUSES, type ScreeningStatus } from '@/api/types'
import { DeidText, PrivacyNote, Pseudonym } from '@/components/common/deid'
import { FitRing } from '@/components/common/score'
import { SessionStatusBadge } from '@/components/common/status'
import { ErrorState } from '@/components/common/states'
import { Badge, Separator, Skeleton } from '@/components/ui/basic'
import { Segmented, SegmentedItem } from '@/components/ui/form'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/overlay'
import { parseRationale, SCREENING_STATUS_LABEL } from '@/lib/labels'
import { formatDate, formatDateTime } from '@/lib/time'

function Section({ title, icon: Icon, children }: { title: string; icon?: typeof BotIcon; children: React.ReactNode }) {
  return (
    <section className="space-y-2.5">
      <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
        {Icon && <Icon className="size-4 text-muted-foreground" aria-hidden />}
        {title}
      </h3>
      {children}
    </section>
  )
}

function Body({ applicationId, postingId }: { applicationId: string; postingId: string }) {
  const q = useApplication(applicationId)
  const update = useUpdateScreening(postingId)
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (q.isPending) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-14 w-60" />
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-32" />
        <Skeleton className="h-48" />
      </div>
    )
  }
  const { candidate, screening, application, sessions, posting } = q.data
  const p = application.profile
  const r = screening ? parseRationale(screening.rationale) : null

  const change = (status: ScreeningStatus) => {
    if (!screening || status === screening.status) return
    update.mutate(
      { screeningId: screening.id, status },
      {
        onSuccess: () =>
          toast.success(`${candidate.pseudonym} → ${SCREENING_STATUS_LABEL[status]}`, { description: '변경 내역은 감사 로그에 남습니다.' }),
        onError: (e) => toast.error('상태를 바꾸지 못했습니다', { description: e instanceof ApiError ? e.message : undefined }),
      },
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-4 pr-8">
        {screening && <FitRing value={screening.fit_score} size={60} />}
        <div className="min-w-0">
          <SheetTitle asChild>
            <h2>
              <Pseudonym value={candidate.pseudonym} size="lg" />
            </h2>
          </SheetTitle>
          <SheetDescription className="mt-0.5 truncate">
            {posting.title} · 접수 {formatDate(application.created_at)}
          </SheetDescription>
        </div>
      </div>

      {screening && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[13px] font-medium">선별 상태</span>
            <Segmented
              type="single"
              value={screening.status}
              onValueChange={(v) => v && change(v as ScreeningStatus)}
              aria-label="선별 상태 변경"
              disabled={update.isPending}
            >
              {SCREENING_STATUSES.map((s) => (
                <SegmentedItem key={s} value={s}>
                  {SCREENING_STATUS_LABEL[s]}
                </SegmentedItem>
              ))}
            </Segmented>
          </div>
          <p className="text-xs text-muted-foreground">AI 적합도는 참고용입니다. 통과·보류·탈락은 사람이 확정하고, 바꾼 내역은 감사 로그에 남습니다.</p>
        </div>
      )}

      {r && screening && (
        <Section title="선별 근거" icon={BotIcon}>
          <div className="rounded-lg border bg-subtle p-4">
            <p className="text-[13.5px] leading-relaxed">
              <DeidText text={r.summary} />
            </p>
            {r.strengths.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-[13px]">
                {r.strengths.map((s) => (
                  <li key={s} className="flex gap-2">
                    <span className="font-semibold text-success" aria-label="강점">
                      +
                    </span>
                    <DeidText text={s} />
                  </li>
                ))}
              </ul>
            )}
            {r.concerns.length > 0 && (
              <ul className="mt-2 space-y-1.5 text-[13px] text-muted-foreground">
                {r.concerns.map((s) => (
                  <li key={s} className="flex gap-2">
                    <span className="font-semibold text-warning" aria-label="확인 필요">
                      −
                    </span>
                    <DeidText text={s} />
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 font-mono text-[11px] text-muted-foreground">
              {screening.model} · {screening.prompt_version} · {formatDateTime(screening.created_at)}
            </p>
          </div>
        </Section>
      )}

      {p && (
        <>
          <Separator />
          <Section title="구조화 프로필">
            <p className="text-[13.5px] leading-relaxed">
              <DeidText text={p.summary} />
            </p>
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline">경력 {p.years_experience}년</Badge>
              {p.skills.map((s) => (
                <Badge key={s} variant="secondary">
                  {s}
                </Badge>
              ))}
            </div>
          </Section>
          <Section title="경력" icon={BriefcaseIcon}>
            <ol className="relative space-y-4 border-l pl-4">
              {p.experience.map((e) => (
                <li key={e.company + e.period} className="relative">
                  <span className="absolute top-1.5 -left-[21px] size-2.5 rounded-full border-2 border-card bg-muted-foreground/60" aria-hidden />
                  <p className="text-[13.5px] font-medium">
                    <DeidText text={e.company} /> · {e.role}
                  </p>
                  <p className="text-xs text-muted-foreground">{e.period}</p>
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[13px] text-muted-foreground marker:text-muted-foreground/50">
                    {e.highlights.map((h) => (
                      <li key={h}>
                        <DeidText text={h} />
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </Section>
          <div className="grid gap-6 sm:grid-cols-2">
            <Section title="학력" icon={GraduationCapIcon}>
              {p.education.map((e) => (
                <p key={e.school + e.major} className="text-[13px]">
                  <DeidText text={e.school} /> <span className="text-muted-foreground">{e.degree} · {e.major}</span>
                </p>
              ))}
            </Section>
            <Section title="자격">
              <p className="text-[13px] text-muted-foreground">{p.certifications.length > 0 ? p.certifications.join(', ') : '없음'}</p>
            </Section>
          </div>
          {p.projects.length > 0 && (
            <Section title="프로젝트" icon={FolderGit2Icon}>
              {p.projects.map((pr) => (
                <div key={pr.name} className="rounded-lg border p-3">
                  <p className="text-[13px] font-medium">{pr.name}</p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">
                    <DeidText text={pr.description} />
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {pr.tech.map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </Section>
          )}
        </>
      )}

      <Separator />
      <Section title="면접" icon={CalendarIcon}>
        {sessions.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">잡힌 면접이 없습니다. 통과 처리 후 면접관 스케줄에서 일정을 잡을 수 있습니다.</p>
        ) : (
          <ul className="space-y-1.5">
            {sessions.map((s) => (
              <li key={s.id}>
                <Link
                  to={s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`}
                  className="flex items-center gap-3 rounded-lg border px-3 py-2 text-[13px] transition-colors hover:bg-subtle"
                >
                  <SessionStatusBadge status={s.status} />
                  <span>{s.scheduled_at && formatDateTime(s.scheduled_at)}</span>
                  <ArrowRightIcon className="ml-auto size-4 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <PrivacyNote />
    </div>
  )
}

export function ApplicationSheet({
  applicationId,
  postingId,
  onClose,
}: {
  applicationId: string | null
  postingId: string
  onClose: () => void
}) {
  return (
    <Sheet open={applicationId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="overflow-y-auto scrollbar-thin" aria-describedby={undefined}>
        {applicationId && <Body applicationId={applicationId} postingId={postingId} />}
      </SheetContent>
    </Sheet>
  )
}
