import { CircleAlertIcon, QuoteIcon } from 'lucide-react'

import type { Evaluation } from '@/api/types'
import { DeidText } from '@/components/common/deid'
import { Badge } from '@/components/ui/basic'
import { confidenceLabel, LOW_CONFIDENCE } from '@/lib/scoring'
import { cn, formatScore } from '@/lib/utils'

function ConfidenceMeter({ value }: { value: number }) {
  const low = value < LOW_CONFIDENCE
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" title={`신뢰도 ${value.toFixed(2)}`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', low ? 'bg-warning' : 'bg-series-1')} style={{ width: `${value * 100}%` }} />
      </span>
      <span className={cn('tabular', low && 'font-medium text-warning')}>
        신뢰도 {confidenceLabel(value)} {value.toFixed(2)}
      </span>
    </span>
  )
}

/** AI scores per competency with the quoted evidence for every item score (FR-07: 근거 인용 필수). */
export function AiEvidence({ ev }: { ev: Evaluation }) {
  const competencies = ev.competency_set?.competencies ?? []
  const qaById = new Map(ev.qa_items.map((q) => [q.id, q]))
  return (
    <div className="space-y-4">
      {competencies.map((c) => {
        const summary = ev.ai.summary.find((s) => s.competency === c.name)
        const items = ev.ai.scores.filter((s) => s.competency === c.name)
        return (
          <div key={c.name} className="rounded-lg border p-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <h4 className="text-sm font-semibold">{c.name}</h4>
              {summary ? (
                <>
                  <span className="text-sm">
                    <span className="text-muted-foreground">AI </span>
                    <span className="font-semibold tabular">{formatScore(summary.score)}</span>
                    <span className="text-muted-foreground"> / 5 · 답변 {summary.item_count}개</span>
                  </span>
                  <ConfidenceMeter value={summary.confidence} />
                  {summary.confidence < LOW_CONFIDENCE && (
                    <Badge variant="warning">
                      <CircleAlertIcon />
                      면접관 검토 필요
                    </Badge>
                  )}
                </>
              ) : (
                <span className="text-xs text-muted-foreground">이 역량을 다룬 답변이 없어 AI가 채점하지 않았습니다 (근거 없는 점수는 저장하지 않음)</span>
              )}
            </div>
            {items.length > 0 && (
              <ul className="mt-3 space-y-2.5">
                {items.map((s) => {
                  const qa = qaById.get(s.qa_item_id)
                  return (
                    <li key={s.id} className="flex gap-3">
                      <span className="mt-0.5 w-9 shrink-0 font-mono text-[11px] font-semibold text-muted-foreground">Q{qa?.seq}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <span className="text-[13px] font-semibold tabular">{s.score}점</span>
                          {s.confidence != null && <ConfidenceMeter value={s.confidence} />}
                        </div>
                        <blockquote className="mt-1.5 flex gap-1.5 border-l-2 border-brand-border pl-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
                          <QuoteIcon className="mt-1 size-3 shrink-0" aria-hidden />
                          <DeidText text={s.evidence ?? ''} />
                        </blockquote>
                        {qa && <p className="mt-1 truncate text-[11.5px] text-muted-foreground/80">질문: {qa.question}</p>}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )
      })}
    </div>
  )
}
