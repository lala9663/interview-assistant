import { CircleAlertIcon, RotateCwIcon, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
  compact?: boolean
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2 py-8' : 'gap-3 py-14', className)}>
      <div className="relative">
        <div className="absolute inset-0 -m-3 rounded-full bg-dots opacity-70 [mask-image:radial-gradient(circle,black_40%,transparent_70%)]" />
        <div className="relative flex size-10 items-center justify-center rounded-xl border bg-card shadow-soft">
          <Icon className="size-[18px] text-muted-foreground" aria-hidden />
        </div>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description && <p className="mx-auto max-w-sm text-[13px] leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : '알 수 없는 오류입니다.'
  const status = error instanceof ApiError && error.status ? ` · ${error.status}` : ''
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center gap-3 py-14 text-center', className)}>
      <div className="flex size-10 items-center justify-center rounded-xl border border-[color-mix(in_oklch,var(--danger)_30%,transparent)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]">
        <CircleAlertIcon className="size-[18px] text-danger" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">불러오지 못했습니다</p>
        <p className="text-[13px] text-muted-foreground">
          {message}
          {status}
        </p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCwIcon />
          다시 시도
        </Button>
      )}
    </div>
  )
}
