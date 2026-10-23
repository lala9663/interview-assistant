import { ArrowDownIcon, CornerDownLeftIcon, PenLineIcon, RotateCwIcon, WifiOffIcon } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { QAItem, TranscriptSegment } from '@/api/types'
import { DeidText } from '@/components/common/deid'
import { Badge, Textarea } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'
import { formatElapsed } from '@/lib/time'
import { cn } from '@/lib/utils'

import { buildTurns, submitOnEnter } from './transcript-utils'
import type { Connection } from './use-transcript'

function SpeakerLabel({ speaker, ms }: { speaker: 'interviewer' | 'candidate'; ms: number }) {
  return (
    <div className="w-[68px] shrink-0 pt-0.5">
      <div className={cn('text-[12px] font-semibold', speaker === 'interviewer' ? 'text-brand' : 'text-foreground')}>
        {speaker === 'interviewer' ? '면접관' : '지원자'}
      </div>
      <div className="text-[11px] text-muted-foreground tabular">{formatElapsed(ms)}</div>
    </div>
  )
}

export function TranscriptView({
  segments,
  partial,
  qaItems,
  listening,
}: {
  segments: TranscriptSegment[]
  partial: TranscriptSegment | null
  qaItems: QAItem[]
  listening: boolean
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)
  const turns = buildTurns(segments, partial)
  const qaById = new Map(qaItems.map((q) => [q.id, q]))
  const contentKey = `${segments.length}:${partial?.text.length ?? 0}`

  useLayoutEffect(() => {
    const el = viewportRef.current
    if (el && pinned) el.scrollTop = el.scrollHeight
  }, [contentKey, pinned])

  const onScroll = () => {
    const el = viewportRef.current
    if (!el) return
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
  }

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={viewportRef} onScroll={onScroll} className="h-full overflow-y-auto px-5 py-4 scrollbar-thin" aria-live="polite" aria-label="실시간 트랜스크립트">
        {turns.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
            <p>아직 전사된 내용이 없습니다.</p>
            <p>왼쪽 사전 질문이나 아래 입력창으로 첫 질문을 기록하세요.</p>
          </div>
        )}
        <ol className="space-y-1">
          {turns.map((t) => {
            const qa = t.qaId ? qaById.get(t.qaId) : undefined
            return (
              <li key={t.key}>
                {t.speaker === 'interviewer' && qa && (
                  <div className="mt-4 mb-1.5 flex items-center gap-2 first:mt-0">
                    <span className="font-mono text-[11px] font-semibold text-muted-foreground">Q{qa.seq}</span>
                    <Badge variant={qa.question_source === 'ai_suggested' ? 'brand' : 'outline'} className="py-0 text-[10.5px]">
                      {QUESTION_SOURCE_LABEL[qa.question_source]}
                    </Badge>
                    <span className="h-px flex-1 bg-border" aria-hidden />
                  </div>
                )}
                <div className={cn('flex gap-3 rounded-lg px-3 py-2.5', t.speaker === 'interviewer' && 'bg-subtle')}>
                  <SpeakerLabel speaker={t.speaker} ms={t.startMs} />
                  <p className={cn('min-w-0 flex-1 text-[14px] leading-[1.75]', t.speaker === 'interviewer' && 'font-medium')}>
                    {t.parts.map((p, i) => (
                      <span key={p.id} className={cn('transition-colors duration-300', !p.final && 'text-muted-foreground/70')}>
                        {i > 0 && ' '}
                        <DeidText text={p.text} />
                        {!p.final && <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-caret bg-foreground/50" aria-hidden />}
                      </span>
                    ))}
                  </p>
                </div>
              </li>
            )
          })}
        </ol>
        {listening && !partial && (
          <div className="mt-2 flex items-center gap-2 px-3 text-xs text-muted-foreground">
            <span className="flex gap-0.5" aria-hidden>
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="size-1 rounded-full bg-muted-foreground"
                  animate={{ opacity: [0.25, 1, 0.25] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.18 }}
                />
              ))}
            </span>
            지원자 답변을 듣는 중
          </div>
        )}
      </div>
      {!pinned && (
        <Button
          size="xs"
          variant="secondary"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
          onClick={() => {
            const el = viewportRef.current
            if (el) el.scrollTop = el.scrollHeight
            setPinned(true)
          }}
        >
          <ArrowDownIcon />
          최신 전사로
        </Button>
      )}
    </div>
  )
}

/** Manual mode: questions and typed answers (no recording / STT down). */
export function ManualLog({ qaItems }: { qaItems: QAItem[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [qaItems.length])
  return (
    <div ref={ref} className="min-h-0 flex-1 overflow-y-auto px-5 py-4 scrollbar-thin">
      {qaItems.length === 0 && (
        <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
          <PenLineIcon className="size-5" aria-hidden />
          <p>수기 모드입니다. 질문을 기록한 뒤 답변 요지를 직접 입력하세요.</p>
        </div>
      )}
      <ol className="space-y-3">
        {qaItems.map((q) => (
          <li key={q.id} className="rounded-lg border bg-card p-3.5">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="font-mono text-[11px] font-semibold text-muted-foreground">Q{q.seq}</span>
              <Badge variant={q.question_source === 'ai_suggested' ? 'brand' : 'outline'} className="py-0 text-[10.5px]">
                {QUESTION_SOURCE_LABEL[q.question_source]}
              </Badge>
            </div>
            <p className="text-[14px] font-medium">{q.question}</p>
            <p className={cn('mt-2 text-[13.5px] leading-relaxed', !q.answer_deidentified && 'text-muted-foreground italic')}>
              {q.answer_deidentified ? <DeidText text={q.answer_deidentified} /> : '답변 미기록'}
            </p>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function ConnectionBanner({ connection, onReconnect }: { connection: Connection; onReconnect: () => void }) {
  if (connection !== 'error' && connection !== 'reconnecting') return null
  return (
    <div
      role="status"
      className="mx-4 mt-3 flex items-center gap-2.5 rounded-lg border border-[color-mix(in_oklch,var(--warning)_35%,transparent)] bg-[color-mix(in_oklch,var(--warning)_9%,transparent)] px-3 py-2 text-[12.5px]"
    >
      <WifiOffIcon className="size-4 shrink-0 text-warning" aria-hidden />
      <span className="flex-1">
        {connection === 'reconnecting'
          ? '전사 연결이 끊겨 다시 연결하는 중입니다. 녹음은 계속됩니다.'
          : '전사 연결이 끊겼습니다. 녹음은 계속되며, 답변은 아래에 수기로 기록할 수 있습니다.'}
      </span>
      {connection === 'error' && (
        <Button size="xs" variant="outline" onClick={onReconnect}>
          <RotateCwIcon />
          다시 연결
        </Button>
      )}
    </div>
  )
}

export function QuestionComposer({ onSubmit, disabled, pending }: { onSubmit: (text: string) => void; disabled: boolean; pending: boolean }) {
  const [text, setText] = useState('')
  const submit = () => {
    const t = text.trim()
    if (!t || disabled || pending) return
    onSubmit(t)
    setText('')
  }
  return (
    <div className="border-t bg-card/60 p-3">
      <div className="flex items-end gap-2 rounded-lg border bg-card p-1.5 pl-3 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/25">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => submitOnEnter(e, submit)}
          rows={1}
          disabled={disabled}
          placeholder="직접 질문 입력 — Enter로 기록, Shift+Enter 줄바꿈"
          aria-label="직접 질문 입력"
          className="max-h-32 min-h-8 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50 [field-sizing:content]"
        />
        <Button size="sm" onClick={submit} disabled={disabled || pending || !text.trim()}>
          <CornerDownLeftIcon />
          질문 기록
        </Button>
      </div>
    </div>
  )
}

export function ManualAnswerBox({ qa, onSave, pending }: { qa: QAItem; onSave: (answer: string) => void; pending: boolean }) {
  const [text, setText] = useState('')
  const save = () => {
    const t = text.trim()
    if (!t || pending) return
    onSave(t)
    setText('')
  }
  return (
    <div className="border-t bg-[color-mix(in_oklch,var(--warning)_5%,transparent)] px-3 pt-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
        <PenLineIcon className="size-3.5 text-warning" aria-hidden />
        Q{qa.seq} 답변 수기 기록
        <span className="font-normal text-muted-foreground">· 저장하면 비식별화 후 꼬리질문 제안에 쓰입니다</span>
      </p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
            e.preventDefault()
            save()
          }
        }}
        placeholder="지원자 답변의 요지를 입력하세요 (Ctrl+Enter 저장)"
        aria-label={`Q${qa.seq} 답변 입력`}
        className="min-h-20 bg-card"
      />
      <div className="flex justify-end py-2">
        <Button size="sm" variant="secondary" onClick={save} disabled={pending || !text.trim()}>
          답변 저장
        </Button>
      </div>
    </div>
  )
}
