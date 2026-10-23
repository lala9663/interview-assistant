import type { SessionInterviewerView } from '@/api/types'
import { Tooltip } from '@/components/ui/overlay'
import { ROLE_LABEL } from '@/lib/labels'
import { cn } from '@/lib/utils'

export function Initial({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        'flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-card bg-muted text-[10.5px] font-semibold text-foreground',
        className,
      )}
    >
      {name.slice(0, 1)}
    </span>
  )
}

export function PanelAvatars({ panel, className }: { panel: SessionInterviewerView[]; className?: string }) {
  return (
    <Tooltip content={panel.map((p) => `${p.interviewer.name} (${ROLE_LABEL[p.role]})`).join(', ')}>
      <span className={cn('flex -space-x-1.5', className)} tabIndex={0} aria-label={`면접관 ${panel.map((p) => p.interviewer.name).join(', ')}`}>
        {panel.map((p) => (
          <Initial key={p.interviewer_id} name={p.interviewer.name} className={p.role === 'lead' ? 'ring-1 ring-brand-border' : undefined} />
        ))}
      </span>
    </Tooltip>
  )
}
