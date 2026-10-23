import { ArrowLeftIcon, BotIcon, ChartBarBigIcon, EyeOffIcon, LoaderIcon, MessageSquareTextIcon, TableIcon, UserRoundCheckIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useEvaluation, useMe } from '@/api/queries'
import type { Evaluation } from '@/api/types'
import { DeidText, Pseudonym } from '@/components/common/deid'
import { FadeIn } from '@/components/common/motion'
import { Page, PageHeader } from '@/components/common/page'
import { AiReferenceNotice } from '@/components/common/score'
import { AiScoringBadge, ModeBadge, SessionStatusBadge } from '@/components/common/status'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem, Switch } from '@/components/ui/form'
import { QUESTION_SOURCE_LABEL, ROLE_LABEL } from '@/lib/labels'
import { formatDateTime, formatDuration, formatRelative } from '@/lib/time'

import { AiEvidence } from './ai-evidence'
import { InterviewerForm } from './interviewer-form'
import { ScoreChart, ScoreTable } from './score-views'
import { seriesColor } from './series'

function AiRunning({ ev }: { ev: Evaluation }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <span className="flex size-10 items-center justify-center rounded-xl border border-brand-border bg-brand-soft">
        <LoaderIcon className="size-[18px] animate-spin text-brand" aria-hidden />
      </span>
      <div>
        <p className="text-sm font-medium">AI가 채점하는 중입니다</p>
        <p className="mt-1 text-[13px] text-muted-foreground">
          비식별 답변 {ev.qa_items.filter((q) => q.answer_deidentified).length}개를 역량 루브릭으로 {ev.ai.samples}회씩 채점해 집계합니다. 근거 인용이 없는 점수는
          저장하지 않습니다.
        </p>
      </div>
    </div>
  )
}

export default function EvaluationPage() {
  const { sessionId = '' } = useParams()
  const q = useEvaluation(sessionId)
  const me = useMe()
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [hideAi, setHideAi] = useState(false)

  if (q.isError) {
    return (
      <Page>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Page>
    )
  }
  if (q.isPending) {
    return (
      <Page>
        <Skeleton className="mb-2 h-3 w-24" />
        <Skeleton className="mb-6 h-7 w-72" />
        <Skeleton className="mb-4 h-16" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </Page>
    )
  }

  const ev = q.data
  const s = ev.session
  const competencies = ev.competency_set?.competencies ?? []
  const mine = ev.interviewers.find((i) => i.interviewer.id === me.data?.id)
  const aiDone = ev.ai.status === 'completed'
  const duration = s.started_at && s.ended_at ? Math.round((new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 60000) : null

  if (s.status !== 'completed') {
    return (
      <Page>
        <EmptyState
          icon={ChartBarBigIcon}
          title="면접이 끝나면 평가가 열립니다"
          description="AI 채점은 면접 종료 후 시작되고, 면접관 점수도 종료 후에 입력합니다."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to={`/sessions/${sessionId}/live`}>면접 화면으로</Link>
            </Button>
          }
        />
      </Page>
    )
  }

  return (
    <Page>
      <PageHeader
        eyebrow={
          <Link to="/sessions" className="inline-flex items-center gap-1 hover:text-foreground">
            <ArrowLeftIcon className="size-3.5" aria-hidden />
            면접 · 평가 결과
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            <Pseudonym value={ev.candidate.pseudonym} size="lg" />
            <span className="text-base font-normal text-muted-foreground">{ev.posting.title}</span>
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {s.started_at && <span>{formatDateTime(s.started_at)}</span>}
            {duration != null && <span>{formatDuration(duration)}</span>}
            <ModeBadge mode={s.mode} />
            <span>질문 {ev.qa_items.length}개</span>
          </span>
        }
        actions={
          <>
            <SessionStatusBadge status={s.status} />
            <AiScoringBadge status={ev.ai.status} />
          </>
        }
      />

      <AiReferenceNotice className="mb-4" />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-4">
          <FadeIn>
            <Card>
              <CardHeader className="flex-wrap">
                <div>
                  <CardTitle>역량별 점수</CardTitle>
                  <CardDescription>AI 점수와 면접관 점수를 나란히 보여 주며 합산하지 않습니다</CardDescription>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Switch id="hide-ai" checked={hideAi} onCheckedChange={setHideAi} />
                    <Label htmlFor="hide-ai" className="flex items-center gap-1 text-xs font-normal text-muted-foreground">
                      <EyeOffIcon className="size-3.5" aria-hidden />
                      AI 점수 가리기
                    </Label>
                  </div>
                  <Segmented type="single" value={view} onValueChange={(v) => v && setView(v as 'chart' | 'table')} aria-label="보기 방식">
                    <SegmentedItem value="chart" aria-label="차트">
                      <ChartBarBigIcon />
                    </SegmentedItem>
                    <SegmentedItem value="table" aria-label="표">
                      <TableIcon />
                    </SegmentedItem>
                  </Segmented>
                </div>
              </CardHeader>
              <CardContent>
                {!aiDone && !hideAi && ev.ai.status === 'running' && (
                  <p className="mb-3 flex items-center gap-1.5 text-xs text-brand">
                    <LoaderIcon className="size-3.5 animate-spin" aria-hidden />
                    AI 채점이 끝나면 AI 막대가 추가됩니다
                  </p>
                )}
                {competencies.length === 0 ? (
                  <EmptyState compact icon={ChartBarBigIcon} title="확정된 역량 사전이 없습니다" />
                ) : view === 'chart' ? (
                  <ScoreChart ev={ev} hideAi={hideAi || !aiDone} />
                ) : (
                  <ScoreTable ev={ev} hideAi={hideAi || !aiDone} />
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.05}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle className="flex items-center gap-1.5">
                    <BotIcon className="size-4 text-brand" aria-hidden />
                    AI 점수 근거
                  </CardTitle>
                  <CardDescription>
                    {ev.ai.model ? `${ev.ai.model} · ${ev.ai.prompt_version} · 답변마다 ${ev.ai.samples}회 채점 후 집계` : 'AI 채점 전'}
                  </CardDescription>
                </div>
                <Badge variant="outline">참고용</Badge>
              </CardHeader>
              <CardContent>
                {hideAi ? (
                  <EmptyState compact icon={EyeOffIcon} title="AI 점수를 가렸습니다" description="내 점수를 먼저 정하고 싶을 때 씁니다. 스위치를 끄면 다시 보입니다." />
                ) : ev.ai.status === 'running' ? (
                  <AiRunning ev={ev} />
                ) : ev.ai.status === 'failed' ? (
                  <EmptyState compact icon={BotIcon} title="AI 채점에 실패했습니다" description="면접관 점수는 그대로 입력할 수 있습니다." />
                ) : (
                  <AiEvidence ev={ev} />
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.1}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle className="flex items-center gap-1.5">
                    <MessageSquareTextIcon className="size-4 text-muted-foreground" aria-hidden />
                    Q&A 기록
                  </CardTitle>
                  <CardDescription>비식별 전사 기준</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <ol className="divide-y">
                  {ev.qa_items.map((qa) => (
                    <li key={qa.id} className="py-3 first:pt-0 last:pb-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] font-semibold text-muted-foreground">Q{qa.seq}</span>
                        <Badge variant={qa.question_source === 'ai_suggested' ? 'brand' : 'outline'} className="py-0 text-[10.5px]">
                          {QUESTION_SOURCE_LABEL[qa.question_source]}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[13.5px] font-medium">{qa.question}</p>
                      <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                        {qa.answer_deidentified ? <DeidText text={qa.answer_deidentified} /> : '답변 없음'}
                      </p>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          </FadeIn>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <FadeIn delay={0.05}>
            <Card className="xl:sticky xl:top-[4.5rem]">
              <CardHeader>
                <div>
                  <CardTitle className="flex items-center gap-1.5">
                    <UserRoundCheckIcon className="size-4 text-muted-foreground" aria-hidden />내 평가
                  </CardTitle>
                  <CardDescription>BARS 기준을 보고 역량마다 점수와 코멘트를 남기세요</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {mine ? (
                  <InterviewerForm key={mine.submitted_at ?? 'new'} sessionId={sessionId} competencies={competencies} mine={mine} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">이 면접의 면접관이 아니어서 점수를 입력할 수 없습니다.</p>
                )}
              </CardContent>
            </Card>
          </FadeIn>

          <FadeIn delay={0.1}>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>면접관별 점수</CardTitle>
                  <CardDescription>면접관마다 따로 저장됩니다</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {ev.interviewers.map((iv, i) => (
                  <div key={iv.interviewer.id}>
                    <div className="flex items-center gap-2">
                      <span className="size-2.5 rounded-[3px]" style={{ background: seriesColor(i + 1) }} aria-hidden />
                      <span className="text-[13px] font-semibold">{iv.interviewer.name}</span>
                      <span className="text-xs text-muted-foreground">{ROLE_LABEL[iv.role]}</span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        {iv.submitted_at ? `${formatRelative(iv.submitted_at)} 제출` : <Badge variant="warning">제출 전</Badge>}
                      </span>
                    </div>
                    {iv.scores.length > 0 && (
                      <ul className="mt-2 space-y-1.5 pl-[18px]">
                        {competencies.map((c) => {
                          const sc = iv.scores.find((x) => x.competency === c.name)
                          if (!sc) return null
                          return (
                            <li key={c.name} className="text-[12.5px]">
                              <span className="text-muted-foreground">{c.name}</span> <span className="font-semibold tabular">{sc.score}</span>
                              {sc.evidence && <p className="text-[12px] leading-snug text-muted-foreground/90">{sc.evidence}</p>}
                            </li>
                          )
                        })}
                      </ul>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          </FadeIn>
        </div>
      </div>
    </Page>
  )
}
