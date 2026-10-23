import { CheckIcon, ChevronDownIcon, CornerDownLeftIcon, HistoryIcon, ListChecksIcon } from 'lucide-react'
import { useState } from 'react'

import type { CandidateCard, PresetQuestion, QAItem } from '@/api/types'
import { DeidText, PrivacyNote, Pseudonym } from '@/components/common/deid'
import { FitRing } from '@/components/common/score'
import { ScreeningBadge } from '@/components/common/status'
import { Badge } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { parseRationale } from '@/lib/labels'
import { formatDate } from '@/lib/time'
import { cn } from '@/lib/utils'

export function CandidateSummary({ card }: { card: CandidateCard }) {
  const [open, setOpen] = useState(false)
  const r = card.screening ? parseRationale(card.screening.rationale) : null
  const p = card.profile
  return (
    <section aria-label="지원자 요약" className="space-y-3">
      <div className="flex items-center gap-3">
        {card.screening && <FitRing value={card.screening.fit_score} size={48} />}
        <div className="min-w-0">
          <Pseudonym value={card.candidate.pseudonym} size="lg" />
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {card.screening && <ScreeningBadge status={card.screening.status} />}
            {p && <Badge variant="outline">경력 {p.years_experience}년</Badge>}
          </div>
        </div>
      </div>

      {p && (
        <>
          <p className="text-[13px] leading-relaxed">
            <DeidText text={p.summary} />
          </p>
          <div className="flex flex-wrap gap-1">
            {p.skills.map((s) => (
              <span key={s} className="rounded-md bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">
                {s}
              </span>
            ))}
          </div>
        </>
      )}

      {r && (
        <div className="rounded-lg border bg-subtle p-3">
          <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">서류 선별 근거 요약 · 참고용</p>
          <ul className="space-y-1.5 text-[12.5px] leading-snug">
            {r.strengths.slice(0, open ? undefined : 2).map((s) => (
              <li key={s} className="flex gap-1.5">
                <span className="mt-0.5 text-success" aria-label="강점">
                  +
                </span>
                <DeidText text={s} />
              </li>
            ))}
            {(open ? r.concerns : r.concerns.slice(0, 1)).map((s) => (
              <li key={s} className="flex gap-1.5 text-muted-foreground">
                <span className="mt-0.5 text-warning" aria-label="확인 필요">
                  −
                </span>
                <DeidText text={s} />
              </li>
            ))}
          </ul>
          {(r.strengths.length > 2 || r.concerns.length > 1 || (p?.experience.length ?? 0) > 0) && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ChevronDownIcon className={cn('size-3.5 transition-transform', open && 'rotate-180')} aria-hidden />
              {open ? '접기' : '경력·학력 더 보기'}
            </button>
          )}
          {open && p && (
            <div className="mt-3 space-y-2 border-t pt-3 text-[12.5px]">
              {p.experience.map((e) => (
                <div key={e.company + e.period}>
                  <div className="font-medium">
                    <DeidText text={e.company} /> · {e.role}
                  </div>
                  <div className="text-[11.5px] text-muted-foreground">{e.period}</div>
                </div>
              ))}
              {p.education.map((e) => (
                <div key={e.school} className="text-muted-foreground">
                  <DeidText text={e.school} /> {e.degree} · {e.major}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <HistoryIcon className="size-3.5" aria-hidden />
        {card.previous_sessions.length > 0
          ? `이전 면접 ${card.previous_sessions.length}회 (${card.previous_sessions.map((s) => (s.ended_at ? formatDate(s.ended_at) : '')).join(', ')})`
          : '이전 면접 기록 없음'}
      </div>
      <PrivacyNote />
    </section>
  )
}

export function PresetQuestions({
  presets,
  qaItems,
  disabled,
  pendingId,
  onAsk,
}: {
  presets: PresetQuestion[]
  qaItems: QAItem[]
  disabled: boolean
  pendingId: string | null
  onAsk: (p: PresetQuestion) => void
}) {
  const askedSeq = new Map<string, number>()
  for (const q of qaItems) {
    if (q.question_source !== 'preset') continue
    const p = presets.find((x) => x.question === q.question)
    if (p) askedSeq.set(p.id, q.seq)
  }
  const groups = new Map<string, PresetQuestion[]>()
  for (const p of presets) groups.set(p.competency, [...(groups.get(p.competency) ?? []), p])

  return (
    <section aria-label="사전 질문" className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
          <ListChecksIcon className="size-4 text-muted-foreground" aria-hidden />
          사전 질문
        </h3>
        <span className="text-xs text-muted-foreground tabular">
          {askedSeq.size}/{presets.length}
        </span>
      </div>
      {presets.length === 0 && <p className="text-[13px] text-muted-foreground">이 공고에는 사전 질문 세트가 없습니다. 직접 질문을 입력하세요.</p>}
      {[...groups.entries()].map(([competency, list]) => (
        <div key={competency} className="space-y-1.5">
          <p className="text-[11.5px] font-medium text-muted-foreground">{competency}</p>
          {list.map((p) => {
            const seq = askedSeq.get(p.id)
            return (
              <div
                key={p.id}
                className={cn(
                  'group rounded-lg border bg-card p-2.5 transition-colors',
                  seq ? 'border-transparent bg-subtle' : 'hover:border-foreground/15',
                )}
              >
                <p className={cn('text-[12.5px] leading-snug', seq && 'text-muted-foreground')}>{p.question}</p>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] text-muted-foreground">{p.intent}</span>
                  {seq ? (
                    <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-success">
                      <CheckIcon className="size-3.5" aria-hidden />Q{seq}
                    </span>
                  ) : (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={disabled || pendingId !== null}
                      onClick={() => onAsk(p)}
                      aria-label={`사전 질문 기록: ${p.question}`}
                    >
                      <CornerDownLeftIcon />
                      {pendingId === p.id ? '기록 중…' : '질문하기'}
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </section>
  )
}
