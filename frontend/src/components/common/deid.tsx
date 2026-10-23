import { LockKeyholeIcon } from 'lucide-react'
import { Fragment } from 'react'

import { Tooltip } from '@/components/ui/overlay'
import { splitTokens } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** A de-identification token rendered as a chip. The original value never reaches the browser. */
export function DeidToken({ token }: { token: string }) {
  return (
    <Tooltip content="비식별 토큰입니다. 원래 값은 원본 영역에만 있고 화면과 AI에는 전달되지 않습니다.">
      <span
        tabIndex={0}
        className="mx-px inline-flex items-center rounded border border-dashed border-foreground/20 bg-muted px-1 py-px align-baseline font-mono text-[0.86em] leading-none text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        {token}
      </span>
    </Tooltip>
  )
}

/** Text with de-identification tokens rendered as chips. */
export function DeidText({ text, className }: { text: string; className?: string }) {
  return (
    <span className={className}>
      {splitTokens(text).map((part, i) =>
        part.token ? <DeidToken key={i} token={part.text} /> : <Fragment key={i}>{part.text}</Fragment>,
      )}
    </span>
  )
}

/** Candidate pseudonym (CAND-0007). Real names are never shown. */
export function Pseudonym({ value, className, size = 'md' }: { value: string; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center font-mono font-semibold tracking-tight tabular',
        size === 'sm' && 'text-[13px]',
        size === 'md' && 'text-sm',
        size === 'lg' && 'text-xl',
        className,
      )}
    >
      {value}
    </span>
  )
}

export function PrivacyNote({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <p className={cn('flex items-start gap-1.5 text-xs text-muted-foreground', className)}>
      <LockKeyholeIcon className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{children ?? '실명과 연락처는 원본 영역에만 있습니다. 화면에는 가명과 비식별 정보만 표시합니다.'}</span>
    </p>
  )
}
