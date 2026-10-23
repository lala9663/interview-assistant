import { InfoIcon, SparklesIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

/** Fit score 0-100 as a small ring. The ring fill is the accent; the number carries the value. */
export function FitRing({ value, size = 44, className }: { value: number; size?: number; className?: string }) {
  const stroke = size >= 56 ? 5 : 4
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  return (
    <div className={cn('relative inline-flex shrink-0 items-center justify-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - value / 100)}
          className="transition-[stroke-dashoffset] duration-700"
        />
      </svg>
      <span className={cn('absolute font-semibold tabular', size >= 56 ? 'text-base' : 'text-[13px]')}>{Math.round(value)}</span>
      <span className="sr-only">적합도 {Math.round(value)}점</span>
    </div>
  )
}

/** Inline fit score bar for tables. */
export function FitBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-7 text-right text-sm font-semibold tabular">{Math.round(value)}</span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div className="h-full rounded-full bg-series-1" style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}

/** Mandatory notice wherever AI scores appear (FR-07, 개인정보보호법 제37조의2). */
export function AiReferenceNotice({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <div
      role="note"
      className={cn(
        'flex items-start gap-2.5 rounded-lg border border-[color-mix(in_oklch,var(--warning)_35%,transparent)] bg-[color-mix(in_oklch,var(--warning)_9%,transparent)] text-[13px] leading-relaxed',
        compact ? 'px-3 py-2' : 'px-4 py-3',
        className,
      )}
    >
      <InfoIcon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <div>
        <p className="font-semibold">AI 점수는 참고용이며 최종 판단은 면접관이 합니다.</p>
        {!compact && (
          <p className="text-muted-foreground">
            AI 점수와 면접관 점수는 따로 저장하고 합산하지 않습니다. AI 점수에는 답변 근거 인용과 신뢰도가 함께 붙습니다.
          </p>
        )}
      </div>
    </div>
  )
}

/** "AI 제안" marker: suggestions are never asked automatically (FR-06). */
export function AiLabel({ children = 'AI 제안', className }: { children?: React.ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 text-xs font-medium text-brand', className)}>
      <SparklesIcon className="size-3.5" aria-hidden />
      {children}
    </span>
  )
}

/** 1-5 score shown as five pips + number. */
export function ScorePips({ score, max = 5, tone = 'ai' }: { score: number | null; max?: number; tone?: 'ai' | 'human' }) {
  const filled = score == null ? 0 : Math.round(score)
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="flex gap-0.5" aria-hidden>
        {Array.from({ length: max }, (_, i) => (
          <span
            key={i}
            className={cn(
              'h-2.5 w-1.5 rounded-sm',
              i < filled ? (tone === 'ai' ? 'bg-series-1' : 'bg-series-2') : 'bg-muted',
            )}
          />
        ))}
      </span>
      <span className="text-sm font-semibold tabular">{score == null ? '–' : Number.isInteger(score) ? score : score.toFixed(1)}</span>
    </span>
  )
}
