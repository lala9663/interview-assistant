/** Icon + badge variant per status. Status colors always ship with an icon and a label. */
import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleOffIcon,
  CirclePauseIcon,
  CircleXIcon,
  ClipboardPenLineIcon,
  ClockIcon,
  GavelIcon,
  MonitorIcon,
  UsersIcon,
} from '@lucide/vue'
import type { Component } from 'vue'

import type { ScreeningStatus, SessionMode, SessionStatus, StepStatus } from '@/api/types'
import type { BadgeVariants } from '@/components/ui/badge'

type Look = { variant: NonNullable<BadgeVariants['variant']>; icon: Component }

export const SCREENING_LOOK: Record<ScreeningStatus, Look> = {
  passed: { variant: 'success', icon: CircleCheckIcon },
  hold: { variant: 'warning', icon: CirclePauseIcon },
  rejected: { variant: 'danger', icon: CircleXIcon },
}

export const SESSION_LOOK: Record<Exclude<SessionStatus, 'in_progress'>, Look> = {
  scheduled: { variant: 'outline', icon: CircleDashedIcon },
  completed: { variant: 'secondary', icon: CircleCheckIcon },
  cancelled: { variant: 'outline', icon: CircleOffIcon },
}

export const MODE_ICON: Record<SessionMode, Component> = { remote: MonitorIcon, onsite: UsersIcon }

/** A step's status (in_progress is drawn with the live dot instead). */
export const STEP_LOOK: Record<StepStatus, Look> = {
  waiting: { variant: 'outline', icon: CircleDashedIcon },
  scheduled: { variant: 'secondary', icon: ClockIcon },
  in_progress: { variant: 'live', icon: CircleDashedIcon },
  evaluating: { variant: 'outline', icon: ClipboardPenLineIcon },
  deciding: { variant: 'brand', icon: GavelIcon },
  passed: { variant: 'success', icon: CircleCheckIcon },
  hold: { variant: 'warning', icon: CirclePauseIcon },
  rejected: { variant: 'danger', icon: CircleXIcon },
}
