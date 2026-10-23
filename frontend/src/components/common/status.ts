/** Icon + badge variant per status. Status colors always ship with an icon and a label. */
import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleOffIcon,
  CirclePauseIcon,
  CircleXIcon,
  MonitorIcon,
  UsersIcon,
} from '@lucide/vue'
import type { Component } from 'vue'

import type { ScreeningStatus, SessionMode, SessionStatus } from '@/api/types'
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
