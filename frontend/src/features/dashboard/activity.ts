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
} from '@lucide/vue'
import type { Component } from 'vue'

import type { ActivityItem, QuestionSource, ScreeningStatus } from '@/api/types'
import { QUESTION_SOURCE_LABEL, SCREENING_STATUS_LABEL } from '@/lib/labels'

/** One run of text in an activity line: plain, emphasised (`strong`), a pseudonym, or muted. */
export interface Part {
  kind: 'text' | 'strong' | 'pseudo' | 'muted'
  text: string
}

const t = (text: string): Part => ({ kind: 'text', text })
const T = (text: string): Part => ({ kind: 'strong', text })
const P = (text: string): Part => ({ kind: 'pseudo', text })

export function describeActivity(a: ActivityItem): { icon: Component; ai?: boolean; parts: Part[] } {
  const target = a.target_label ?? ''
  const actor = a.actor_label
  const d = a.details ?? {}
  switch (a.action) {
    case 'screening.batch_completed':
      return { icon: BotIcon, ai: true, parts: [t('AI가 '), T(target), t(` 지원서 ${String(d.count ?? '')}건 선별을 마쳤습니다`)] }
    case 'screening.status_changed':
      return {
        icon: FilePenIcon,
        parts: [
          T(actor),
          t('님이 '),
          P(target),
          t(` 서류 상태를 ${SCREENING_STATUS_LABEL[d.from as ScreeningStatus] ?? ''} → `),
          T(SCREENING_STATUS_LABEL[d.to as ScreeningStatus] ?? ''),
          t('(으)로 바꿨습니다'),
        ],
      }
    case 'competency_set.generated':
      return { icon: BotIcon, ai: true, parts: [t('AI가 '), T(target), t(' 역량 사전 초안을 만들었습니다')] }
    case 'competency_set.approved':
      return { icon: BookCheckIcon, parts: [T(actor), t('님이 '), T(target), t(' 역량 사전을 확정했습니다')] }
    case 'competency_set.created':
    case 'competency_set.updated':
      return { icon: FilePenIcon, parts: [T(actor), t('님이 '), T(target), t(' 역량 사전을 수정했습니다')] }
    case 'consent.recorded':
      return { icon: ShieldCheckIcon, parts: [P(target), t(` 녹음·전사 ${d.consent_recording ? '동의' : '미동의(수기 모드)'}를 기록했습니다`)] }
    case 'session.scheduled':
      return { icon: CalendarPlusIcon, parts: [T(actor), t('님이 '), P(target), t(' 면접 일정을 잡았습니다')] }
    case 'session.started':
      return { icon: MicIcon, parts: [T(actor), t('님이 '), P(target), t(' 면접을 시작했습니다')] }
    case 'session.completed':
      return { icon: SquareStopIcon, parts: [T(actor), t('님이 '), P(target), t(' 면접을 마쳤습니다')] }
    case 'qa.created':
      return {
        icon: MessageSquarePlusIcon,
        parts: [
          P(target),
          t(' 면접에 질문을 기록했습니다'),
          ...(typeof d.question_source === 'string'
            ? [{ kind: 'muted', text: ` · ${QUESTION_SOURCE_LABEL[d.question_source as QuestionSource]}` } satisfies Part]
            : []),
        ],
      }
    case 'score.ai_started':
      return { icon: BotIcon, ai: true, parts: [P(target), t(' AI 채점을 시작했습니다')] }
    case 'score.ai_completed':
      return { icon: CircleCheckIcon, ai: true, parts: [P(target), t(' AI 채점이 끝났습니다 (참고용)')] }
    case 'score.interviewer_submitted':
      return { icon: ClipboardCheckIcon, parts: [T(actor), t('님이 '), P(target), t(' 평가를 제출했습니다')] }
    default:
      return { icon: FilePenIcon, parts: [t(a.action)] }
  }
}

/** Actions that are audit-only (every AI call is logged) and too noisy for the feed. */
export const HIDDEN_ACTIONS = new Set(['followup.generated'])
