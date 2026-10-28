import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { useCreateSession } from '@/api/queries'
import type { Interviewer, ScheduleSuggestion, SessionMode } from '@/api/types'
import { roundFullName } from '@/lib/labels'
import { formatDate, formatTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

/** The lead the user picked while they are on the panel, else the panel's first interviewer. */
export const leadOf = (panel: readonly Interviewer[], picked: string) => (panel.some((i) => i.id === picked) ? picked : (panel[0]?.id ?? ''))

export interface Booking {
  applicationId: string
  roundId: string
  slot: ScheduleSuggestion
  panel: readonly Interviewer[]
  mode: SessionMode
  /** the picked lead; see leadOf */
  lead: string
}

/** Turn a slot into a scheduled session (확정 일정) with one lead and the rest as panel. */
export function useBookSession() {
  const router = useRouter()
  const create = useCreateSession()

  function book(b: Booking, onBooked: () => void) {
    const lead = leadOf(b.panel, b.lead)
    create.mutate(
      {
        application_id: b.applicationId,
        round_id: b.roundId,
        mode: b.mode,
        scheduled_at: b.slot.start_at,
        interviewers: b.panel.map((i) => ({ interviewer_id: i.id, role: i.id === lead ? 'lead' : 'panel' })),
      },
      {
        onSuccess: (s) => {
          toast.success(`${s.candidate.pseudonym} ${s.round.label} 면접을 잡았습니다`, {
            description: `${formatDate(b.slot.start_at)} ${formatTime(b.slot.start_at)} · ${roundFullName(s.round)}`,
            action: { label: '보기', onClick: () => void router.push('/sessions') },
          })
          onBooked()
        },
        onError: toastError('일정을 잡지 못했습니다'),
      },
    )
  }

  return { create, book }
}
