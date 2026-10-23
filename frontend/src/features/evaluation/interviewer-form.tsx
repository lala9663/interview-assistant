import { CheckIcon, SendIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useSubmitScores } from '@/api/queries'
import { BARS_LEVELS, type BarsLevel, type Competency, type InterviewerEvaluation } from '@/api/types'
import { Textarea } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem } from '@/components/ui/form'
import { Tooltip } from '@/components/ui/overlay'
import { formatRelative } from '@/lib/time'

interface Row {
  score: number | null
  comment: string
}

/** The signed-in interviewer's own scores and comments (FR-08). Stored apart from AI scores. */
export function InterviewerForm({
  sessionId,
  competencies,
  mine,
}: {
  sessionId: string
  competencies: Competency[]
  mine: InterviewerEvaluation
}) {
  const submit = useSubmitScores(sessionId)
  const [rows, setRows] = useState<Record<string, Row>>(() =>
    Object.fromEntries(
      competencies.map((c) => {
        const s = mine.scores.find((x) => x.competency === c.name)
        return [c.name, { score: s?.score ?? null, comment: s?.evidence ?? '' }]
      }),
    ),
  )
  const missing = competencies.filter((c) => rows[c.name]?.score == null).length
  const set = (name: string, patch: Partial<Row>) => setRows((r) => ({ ...r, [name]: { ...r[name]!, ...patch } }))

  const onSubmit = () =>
    submit.mutate(
      {
        interviewerId: mine.interviewer.id,
        body: { scores: competencies.map((c) => ({ competency: c.name, score: rows[c.name]!.score!, comment: rows[c.name]!.comment })) },
      },
      {
        onSuccess: () => toast.success(mine.submitted_at ? '평가를 수정했습니다' : '평가를 제출했습니다', { description: 'AI 점수와 따로 저장되었습니다.' }),
        onError: (e) => toast.error('제출하지 못했습니다', { description: e instanceof ApiError ? e.message : undefined }),
      },
    )

  return (
    <div className="space-y-4">
      {competencies.map((c) => {
        const row = rows[c.name]!
        return (
          <fieldset key={c.name} className="space-y-2">
            <legend className="flex w-full items-baseline justify-between gap-2">
              <span className="text-[13px] font-semibold">{c.name}</span>
              <span className="text-[11px] text-muted-foreground">1~5점</span>
            </legend>
            <Segmented
              type="single"
              value={row.score ? String(row.score) : ''}
              onValueChange={(v) => v && set(c.name, { score: Number(v) })}
              className="grid w-full grid-cols-5"
              aria-label={`${c.name} 점수`}
            >
              {BARS_LEVELS.map((l) => (
                <Tooltip key={l} content={c.bars[l]}>
                  <SegmentedItem value={l} aria-label={`${l}점: ${c.bars[l]}`} className="tabular aria-checked:bg-primary aria-checked:text-primary-foreground dark:aria-checked:bg-primary">
                    {l}
                  </SegmentedItem>
                </Tooltip>
              ))}
            </Segmented>
            {row.score != null && (
              <p className="rounded-md bg-subtle px-2.5 py-1.5 text-[12px] leading-snug text-muted-foreground">
                <span className="font-medium text-foreground">{row.score}점 기준</span> · {c.bars[String(row.score) as BarsLevel]}
              </p>
            )}
            <Textarea
              value={row.comment}
              onChange={(e) => set(c.name, { comment: e.target.value })}
              placeholder="근거가 된 답변과 관찰을 적어 주세요"
              aria-label={`${c.name} 코멘트`}
              className="min-h-14 text-[13px]"
            />
          </fieldset>
        )
      })}
      <div className="flex items-center justify-between gap-3 border-t pt-4">
        <span className="text-xs text-muted-foreground">
          {mine.submitted_at ? (
            <span className="inline-flex items-center gap-1 text-success">
              <CheckIcon className="size-3.5" aria-hidden />
              {formatRelative(mine.submitted_at)} 제출
            </span>
          ) : missing > 0 ? (
            `${missing}개 역량 점수가 남았습니다`
          ) : (
            '모든 역량에 점수를 매겼습니다'
          )}
        </span>
        <Button onClick={onSubmit} disabled={missing > 0 || submit.isPending}>
          <SendIcon />
          {submit.isPending ? '저장 중…' : mine.submitted_at ? '수정 제출' : '평가 제출'}
        </Button>
      </div>
    </div>
  )
}
