import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleDotIcon,
  CircleOffIcon,
  CirclePauseIcon,
  CircleXIcon,
  LoaderIcon,
  MonitorIcon,
  UsersIcon,
} from 'lucide-react'

import type { AiScoringStatus, ApplicationStage, ScreeningStatus, SessionMode, SessionStatus } from '@/api/types'
import { Badge } from '@/components/ui/basic'
import { AI_SCORING_LABEL, SCREENING_STATUS_LABEL, SESSION_MODE_LABEL, SESSION_STATUS_LABEL, STAGE_LABEL } from '@/lib/labels'

export function ScreeningBadge({ status }: { status: ScreeningStatus }) {
  const map = {
    passed: { variant: 'success', Icon: CircleCheckIcon },
    hold: { variant: 'warning', Icon: CirclePauseIcon },
    rejected: { variant: 'danger', Icon: CircleXIcon },
  } as const
  const { variant, Icon } = map[status]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden />
      {SCREENING_STATUS_LABEL[status]}
    </Badge>
  )
}

export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  if (status === 'in_progress') {
    return (
      <Badge variant="live">
        <span className="size-1.5 animate-live rounded-full bg-live" aria-hidden />
        {SESSION_STATUS_LABEL[status]}
      </Badge>
    )
  }
  const map = {
    scheduled: { variant: 'outline', Icon: CircleDashedIcon },
    completed: { variant: 'secondary', Icon: CircleCheckIcon },
    cancelled: { variant: 'outline', Icon: CircleOffIcon },
  } as const
  const { variant, Icon } = map[status]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden />
      {SESSION_STATUS_LABEL[status]}
    </Badge>
  )
}

export function ModeBadge({ mode }: { mode: SessionMode }) {
  const Icon = mode === 'remote' ? MonitorIcon : UsersIcon
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Icon className="size-3.5" aria-hidden />
      {SESSION_MODE_LABEL[mode]}
    </span>
  )
}

export function StageBadge({ stage }: { stage: ApplicationStage }) {
  const variant = stage === 'interviewing' ? 'live' : stage === 'evaluated' ? 'success' : stage === 'screening' ? 'outline' : 'brand'
  return (
    <Badge variant={variant}>
      {stage === 'interviewing' ? <span className="size-1.5 rounded-full bg-live" aria-hidden /> : <CircleDotIcon aria-hidden />}
      {STAGE_LABEL[stage]}
    </Badge>
  )
}

export function AiScoringBadge({ status }: { status: AiScoringStatus }) {
  if (status === 'running') {
    return (
      <Badge variant="brand">
        <LoaderIcon className="animate-spin" aria-hidden />
        AI {AI_SCORING_LABEL[status]}
      </Badge>
    )
  }
  if (status === 'failed') return <Badge variant="danger">AI {AI_SCORING_LABEL[status]}</Badge>
  if (status === 'completed') return <Badge variant="outline">AI 채점 완료</Badge>
  return <Badge variant="outline">AI 채점 전</Badge>
}
