import { CheckIcon, PencilLineIcon, QuoteIcon, RefreshCwIcon, SparklesIcon } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'

import { DeidText } from '@/components/common/deid'
import { Badge, Skeleton, Textarea } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/overlay'
import { cn } from '@/lib/utils'

import type { FollowUpState, Suggestion } from './follow-ups'
import { submitOnEnter } from './transcript-utils'

function SuggestionCard({
  s,
  used,
  usedSeq,
  usedEdited,
  otherUsed,
  disabled,
  pending,
  onUse,
}: {
  s: Suggestion
  used: boolean
  usedSeq: number | null
  usedEdited: boolean
  otherUsed: boolean
  disabled: boolean
  pending: boolean
  onUse: (text: string, edited: boolean) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(s.text)
  const submitEdit = () => {
    const t = draft.trim()
    if (!t) return
    onUse(t, t !== s.text)
    setEditing(false)
  }

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: otherUsed ? 0.55 : 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        'rounded-lg border p-3 transition-colors',
        used ? 'border-[color-mix(in_oklch,var(--success)_40%,transparent)] bg-[color-mix(in_oklch,var(--success)_6%,transparent)]' : 'ai-dashed',
      )}
      aria-label={`꼬리질문 후보 ${s.index + 1}`}
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="font-mono text-[10.5px] font-semibold text-muted-foreground">후보 {s.index + 1}</span>
        <Badge variant="outline" className="py-0 text-[10.5px]">
          {s.competency}
        </Badge>
        {used && (
          <Badge variant="success" className="ml-auto py-0 text-[10.5px]">
            <CheckIcon />
            기록됨 · Q{usedSeq}
            {usedEdited && ' · 수정함'}
          </Badge>
        )}
        {otherUsed && <span className="ml-auto text-[10.5px] text-muted-foreground">미채택</span>}
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => submitOnEnter(e, submitEdit)}
            aria-label="꼬리질문 수정"
            className="min-h-20 text-[13px]"
          />
          <div className="flex justify-end gap-1.5">
            <Button size="xs" variant="ghost" onClick={() => (setEditing(false), setDraft(s.text))}>
              취소
            </Button>
            <Button size="xs" onClick={submitEdit} disabled={pending || !draft.trim()}>
              수정한 질문 사용
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[13.5px] leading-relaxed font-medium">
          {s.text}
          {!s.done && <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-caret bg-brand" aria-hidden />}
        </p>
      )}

      {s.done && s.grounding && !editing && (
        <Tooltip content={s.rationale ?? ''} side="left">
          <p tabIndex={0} className="mt-2 flex gap-1.5 border-l-2 border-brand-border pl-2 text-[12px] leading-snug text-muted-foreground outline-none">
            <QuoteIcon className="mt-0.5 size-3 shrink-0" aria-hidden />
            <span className="line-clamp-2">
              <DeidText text={s.grounding} />
            </span>
          </p>
        </Tooltip>
      )}
      {s.done && s.rationale && !editing && <p className="mt-1.5 text-[11.5px] text-muted-foreground">{s.rationale}</p>}

      {s.done && !used && !otherUsed && !editing && (
        <div className="mt-2.5 flex gap-1.5">
          <Button size="xs" onClick={() => onUse(s.text, false)} disabled={disabled || pending}>
            이 질문 사용
          </Button>
          <Button size="xs" variant="ghost" onClick={() => setEditing(true)} disabled={disabled || pending}>
            <PencilLineIcon />
            수정 후 사용
          </Button>
        </div>
      )}
    </motion.li>
  )
}

export function FollowUpPanel({
  state,
  listening,
  hasAnswer,
  disabled,
  pendingSuggestionId,
  onUse,
  onRetry,
}: {
  state: FollowUpState
  listening: boolean
  hasAnswer: boolean
  disabled: boolean
  pendingSuggestionId: string | null
  onUse: (s: Suggestion, text: string, edited: boolean) => void
  onRetry: () => void
}) {
  const streamingEmpty = state.status === 'streaming' && state.suggestions.length === 0
  return (
    <section aria-label="꼬리질문 제안" className="flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <SparklesIcon className="size-4 text-brand" aria-hidden />
            꼬리질문 제안
          </h3>
          <p className="mt-0.5 text-[11.5px] leading-snug text-muted-foreground">
            AI 제안입니다. 자동으로 묻지 않으며, 면접관이 고르거나 고친 질문만 기록됩니다.
          </p>
        </div>
        {(state.status === 'done' || state.status === 'error') && hasAnswer && (
          <Tooltip content="같은 답변으로 후보를 다시 받습니다">
            <Button size="icon-xs" variant="ghost" onClick={onRetry} disabled={disabled} aria-label="다시 제안">
              <RefreshCwIcon />
            </Button>
          </Tooltip>
        )}
      </div>

      <div className="mt-3">
        {state.status === 'error' && (
          <div className="rounded-lg border border-dashed p-3 text-[12.5px]">
            <p className="font-medium">제안을 받지 못했습니다</p>
            <p className="mt-0.5 text-muted-foreground">{state.error} 직접 질문을 입력해 면접을 계속할 수 있습니다.</p>
            <Button size="xs" variant="outline" className="mt-2" onClick={onRetry} disabled={disabled || !hasAnswer}>
              다시 시도
            </Button>
          </div>
        )}

        {state.status === 'idle' && (
          <div className="rounded-lg border border-dashed px-3 py-5 text-center text-[12.5px] text-muted-foreground">
            {listening ? '지원자 답변을 듣는 중입니다. 답변이 끝나면 후보 2~3개를 제안합니다.' : '답변이 끝나면 그 답변을 근거로 꼬리질문 후보가 나타납니다.'}
          </div>
        )}

        {streamingEmpty && (
          <ul className="space-y-2" aria-busy>
            {[0, 1, 2].map((i) => (
              <li key={i} className="rounded-lg border border-dashed p-3">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-2.5 h-3.5 w-full" />
                <Skeleton className="mt-1.5 h-3.5 w-2/3" />
              </li>
            ))}
            <li className="text-center text-[11.5px] text-muted-foreground">직전 답변에서 근거를 찾는 중…</li>
          </ul>
        )}

        {state.suggestions.length > 0 && (
          <ul className="space-y-2">
            <AnimatePresence initial={false}>
              {state.suggestions.map((s) => (
                <SuggestionCard
                  key={s.id}
                  s={s}
                  used={state.used?.suggestionId === s.id}
                  usedSeq={state.used?.suggestionId === s.id ? state.used.seq : null}
                  usedEdited={state.used?.suggestionId === s.id ? state.used.edited : false}
                  otherUsed={Boolean(state.used) && state.used?.suggestionId !== s.id}
                  disabled={disabled}
                  pending={pendingSuggestionId !== null}
                  onUse={(text, edited) => onUse(s, text, edited)}
                />
              ))}
            </AnimatePresence>
            {state.status === 'streaming' &&
              Array.from({ length: Math.max(0, 3 - state.suggestions.length) }, (_, i) => (
                <li key={`sk-${i}`} className="rounded-lg border border-dashed p-3 opacity-60">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="mt-2.5 h-3.5 w-4/5" />
                </li>
              ))}
          </ul>
        )}
        {state.used && listening && (
          <p className="mt-2 text-center text-[11.5px] text-muted-foreground">새 답변이 끝나면 다음 후보를 제안합니다.</p>
        )}
        {state.model && state.status === 'done' && (
          <p className="mt-2 text-right font-mono text-[10.5px] text-muted-foreground/70">{state.model}</p>
        )}
      </div>
    </section>
  )
}
