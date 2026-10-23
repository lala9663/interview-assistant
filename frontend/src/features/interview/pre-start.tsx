import { CheckIcon, MicIcon, MicOffIcon, PlayIcon, ShieldCheckIcon } from 'lucide-react'
import { RadioGroup } from 'radix-ui'
import { useState } from 'react'
import { Link } from 'react-router'

import { useSessionLifecycle } from '@/api/queries'
import type { SessionDetail } from '@/api/types'
import { Pseudonym } from '@/components/common/deid'
import { Page } from '@/components/common/page'
import { ModeBadge } from '@/components/common/status'
import { Badge, Card, CardContent } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { ROLE_LABEL } from '@/lib/labels'
import { formatDateTime, formatRelative } from '@/lib/time'
import { cn } from '@/lib/utils'

import { CandidateSummary } from './candidate-panel'

function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      <span
        className={cn(
          'relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold',
          done ? 'border-transparent bg-success text-white' : 'bg-card',
        )}
      >
        {done ? <CheckIcon className="size-3.5" strokeWidth={3} aria-hidden /> : n}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-sm font-semibold">{title}</p>
        <div className="mt-2">{children}</div>
      </div>
    </li>
  )
}

/** Before the interview: recording consent (FR-05, 녹음 동의) and start. */
export function PreStart({ detail, onStarted }: { detail: SessionDetail; onStarted: () => void }) {
  const lifecycle = useSessionLifecycle(detail.session.id)
  const recorded = detail.card.candidate.consent_at !== null || lifecycle.consent.isSuccess
  const [choice, setChoice] = useState<'yes' | 'no' | null>(recorded ? (detail.card.candidate.consent_recording ? 'yes' : 'no') : null)
  const consentSaved = lifecycle.consent.isSuccess || detail.card.candidate.consent_at !== null
  const consented = detail.card.candidate.consent_recording

  return (
    <Page className="max-w-[1100px]">
      <div className="mb-6">
        <p className="text-xs font-medium text-muted-foreground">면접 준비 · {detail.session.scheduled_at && formatDateTime(detail.session.scheduled_at)}</p>
        <h1 className="mt-1 flex flex-wrap items-center gap-3 text-[22px] font-semibold tracking-tight">
          <Pseudonym value={detail.card.candidate.pseudonym} size="lg" />
          <span className="text-base font-normal text-muted-foreground">{detail.posting.title}</span>
        </h1>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <CardContent className="pt-5">
            <ol className="relative before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-border">
              <Step n={1} title="녹음·전사 동의 확인" done={consentSaved}>
                <p className="mb-3 text-[13px] leading-relaxed text-muted-foreground">
                  녹음과 실시간 전사는 지원자의 사전 동의가 있을 때만 합니다. 동의하지 않으면 녹음 없이 수기 모드로 진행합니다.
                </p>
                <RadioGroup.Root
                  value={choice ?? ''}
                  onValueChange={(v) => setChoice(v as 'yes' | 'no')}
                  className="grid gap-2 sm:grid-cols-2"
                  aria-label="녹음 동의 여부"
                >
                  {(
                    [
                      { v: 'yes', icon: MicIcon, title: '동의함', desc: '녹음과 실시간 전사, 꼬리질문 제안을 켭니다' },
                      { v: 'no', icon: MicOffIcon, title: '동의하지 않음', desc: '녹음 없이 답변을 수기로 기록합니다' },
                    ] as const
                  ).map((o) => (
                    <RadioGroup.Item
                      key={o.v}
                      value={o.v}
                      className="flex items-start gap-3 rounded-lg border bg-card p-3 text-left transition-colors outline-none hover:bg-subtle focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=checked]:border-ring data-[state=checked]:bg-brand-soft"
                    >
                      <o.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span>
                        <span className="block text-[13px] font-medium">{o.title}</span>
                        <span className="block text-xs text-muted-foreground">{o.desc}</span>
                      </span>
                    </RadioGroup.Item>
                  ))}
                </RadioGroup.Root>
                <div className="mt-3 flex items-center gap-3">
                  <Button
                    size="sm"
                    variant={consentSaved ? 'outline' : 'default'}
                    disabled={!choice || lifecycle.consent.isPending}
                    onClick={() => lifecycle.consent.mutate(choice === 'yes')}
                  >
                    <ShieldCheckIcon />
                    {consentSaved ? '동의 다시 기록' : '동의 여부 기록'}
                  </Button>
                  {consentSaved && (
                    <span className="text-xs text-muted-foreground">
                      {consented ? `동의 기록됨 · ${detail.card.candidate.consent_at ? formatRelative(detail.card.candidate.consent_at) : ''}` : '미동의 기록됨 · 수기 모드'}
                    </span>
                  )}
                </div>
              </Step>
              <Step n={2} title="면접 준비 확인" done={consentSaved}>
                <ul className="space-y-1.5 text-[13px]">
                  <li className="flex items-center gap-2">
                    <ModeBadge mode={detail.session.mode} />
                    <span className="text-muted-foreground">
                      {detail.session.mode === 'remote' ? '앱 내 통화는 11단계에서 연결됩니다 (모의 모드에서는 전사만 재생)' : '방 안 마이크 1대 기준'}
                    </span>
                  </li>
                  <li className="flex flex-wrap items-center gap-1.5">
                    <span className="text-muted-foreground">면접관</span>
                    {detail.interviewers.map((p) => (
                      <Badge key={p.interviewer_id} variant="outline">
                        {p.interviewer.name} · {ROLE_LABEL[p.role]}
                      </Badge>
                    ))}
                  </li>
                  <li className="text-muted-foreground">
                    사전 질문 {detail.preset_questions.length}개 · 역량 {detail.competency_set?.competencies.length ?? 0}개
                    {detail.competency_set && ` (역량 사전 v${detail.competency_set.version})`}
                  </li>
                </ul>
              </Step>
              <Step n={3} title="면접 시작" done={false}>
                <p className="mb-3 text-[13px] text-muted-foreground">
                  {consentSaved
                    ? consented
                      ? '시작하면 녹음과 실시간 전사가 켜집니다.'
                      : '시작하면 녹음 없이 수기 모드로 진행합니다.'
                    : '먼저 동의 여부를 기록하세요.'}
                </p>
                <div className="flex gap-2">
                  <Button
                    disabled={!consentSaved || lifecycle.start.isPending}
                    onClick={() => lifecycle.start.mutate(undefined, { onSuccess: onStarted })}
                  >
                    <PlayIcon />
                    {lifecycle.start.isPending ? '시작하는 중…' : '면접 시작'}
                  </Button>
                  <Button asChild variant="ghost">
                    <Link to="/sessions">나중에</Link>
                  </Button>
                </div>
              </Step>
            </ol>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <CandidateSummary card={detail.card} />
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
