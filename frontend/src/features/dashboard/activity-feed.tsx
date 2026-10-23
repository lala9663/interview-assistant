import {
  BookCheckIcon,
  BotIcon,
  CalendarPlusIcon,
  CircleCheckIcon,
  ClipboardCheckIcon,
  FilePenIcon,
  MessageSquarePlusIcon,
  MicIcon,
  ShieldCheckIcon,
  SquareStopIcon,
  type LucideIcon,
} from 'lucide-react'

import type { ActivityItem, ScreeningStatus } from '@/api/types'
import { QUESTION_SOURCE_LABEL, SCREENING_STATUS_LABEL } from '@/lib/labels'
import { formatRelative } from '@/lib/time'
import { cn } from '@/lib/utils'

const T = ({ children }: { children: React.ReactNode }) => <span className="font-medium text-foreground">{children}</span>
const P = ({ children }: { children: React.ReactNode }) => <span className="font-mono text-[12.5px] font-semibold text-foreground">{children}</span>

function describe(a: ActivityItem): { icon: LucideIcon; ai?: boolean; text: React.ReactNode } {
  const target = a.target_label ?? ''
  const d = a.details ?? {}
  switch (a.action) {
    case 'screening.batch_completed':
      return { icon: BotIcon, ai: true, text: <>AI가 <T>{target}</T> 지원서 {String(d.count ?? '')}건 선별을 마쳤습니다</> }
    case 'screening.status_changed':
      return {
        icon: FilePenIcon,
        text: (
          <>
            <T>{a.actor_label}</T>님이 <P>{target}</P> 서류 상태를 {SCREENING_STATUS_LABEL[d.from as ScreeningStatus] ?? ''} →{' '}
            <T>{SCREENING_STATUS_LABEL[d.to as ScreeningStatus] ?? ''}</T>(으)로 바꿨습니다
          </>
        ),
      }
    case 'competency_set.generated':
      return { icon: BotIcon, ai: true, text: <>AI가 <T>{target}</T> 역량 사전 초안을 만들었습니다</> }
    case 'competency_set.approved':
      return { icon: BookCheckIcon, text: <><T>{a.actor_label}</T>님이 <T>{target}</T> 역량 사전을 확정했습니다</> }
    case 'competency_set.created':
    case 'competency_set.updated':
      return { icon: FilePenIcon, text: <><T>{a.actor_label}</T>님이 <T>{target}</T> 역량 사전을 수정했습니다</> }
    case 'consent.recorded':
      return {
        icon: ShieldCheckIcon,
        text: (
          <>
            <P>{target}</P> 녹음·전사 {d.consent_recording ? '동의' : '미동의(수기 모드)'}를 기록했습니다
          </>
        ),
      }
    case 'session.scheduled':
      return { icon: CalendarPlusIcon, text: <><T>{a.actor_label}</T>님이 <P>{target}</P> 면접 일정을 잡았습니다</> }
    case 'session.started':
      return { icon: MicIcon, text: <><T>{a.actor_label}</T>님이 <P>{target}</P> 면접을 시작했습니다</> }
    case 'session.completed':
      return { icon: SquareStopIcon, text: <><T>{a.actor_label}</T>님이 <P>{target}</P> 면접을 마쳤습니다</> }
    case 'qa.created':
      return {
        icon: MessageSquarePlusIcon,
        text: (
          <>
            <P>{target}</P> 면접에 질문을 기록했습니다
            {typeof d.question_source === 'string' && (
              <span className="text-muted-foreground"> · {QUESTION_SOURCE_LABEL[d.question_source as keyof typeof QUESTION_SOURCE_LABEL]}</span>
            )}
          </>
        ),
      }
    case 'score.ai_started':
      return { icon: BotIcon, ai: true, text: <><P>{target}</P> AI 채점을 시작했습니다</> }
    case 'score.ai_completed':
      return { icon: CircleCheckIcon, ai: true, text: <><P>{target}</P> AI 채점이 끝났습니다 (참고용)</> }
    case 'score.interviewer_submitted':
      return { icon: ClipboardCheckIcon, text: <><T>{a.actor_label}</T>님이 <P>{target}</P> 평가를 제출했습니다</> }
    default:
      return { icon: FilePenIcon, text: <>{a.action}</> }
  }
}

/** Actions that are audit-only (every AI call is logged) and too noisy for the feed. */
const HIDDEN = new Set(['followup.generated'])

export function ActivityFeed({ items }: { items: ActivityItem[] }) {
  const visible = items.filter((a) => !HIDDEN.has(a.action))
  return (
    <ol className="relative">
      {visible.map((a, i) => {
        const { icon: Icon, ai, text } = describe(a)
        return (
          <li key={a.id} className="relative flex gap-3 pb-4 last:pb-0">
            {i < visible.length - 1 && <span className="absolute top-7 bottom-0 left-[13px] w-px bg-border" aria-hidden />}
            <span
              className={cn(
                'relative flex size-7 shrink-0 items-center justify-center rounded-full border bg-card',
                ai && 'border-brand-border bg-brand-soft',
              )}
            >
              <Icon className={cn('size-3.5', ai ? 'text-brand' : 'text-muted-foreground')} aria-hidden />
            </span>
            <div className="min-w-0 pt-1">
              <p className="text-[13px] leading-snug text-muted-foreground">{text}</p>
              <p className="mt-0.5 text-[11.5px] text-muted-foreground/80">{formatRelative(a.occurred_at)}</p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
