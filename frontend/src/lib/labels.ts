import type {
  ApplicationStage,
  AiScoringStatus,
  InterviewerRole,
  PostingStatus,
  QuestionSource,
  ScreeningStatus,
  SessionMode,
  SessionStatus,
} from '@/api/types'

export const SCREENING_STATUS_LABEL: Record<ScreeningStatus, string> = {
  passed: '통과',
  hold: '보류',
  rejected: '탈락',
}

export const POSTING_STATUS_LABEL: Record<PostingStatus, string> = {
  draft: '작성 중',
  open: '진행 중',
  closed: '마감',
}

export const SESSION_STATUS_LABEL: Record<SessionStatus, string> = {
  scheduled: '예정',
  in_progress: '진행 중',
  completed: '완료',
  cancelled: '취소',
}

export const SESSION_MODE_LABEL: Record<SessionMode, string> = {
  onsite: '대면',
  remote: '비대면',
}

export const ROLE_LABEL: Record<InterviewerRole, string> = {
  lead: '주관',
  panel: '배석',
}

export const QUESTION_SOURCE_LABEL: Record<QuestionSource, string> = {
  preset: '사전 질문',
  ai_suggested: 'AI 제안',
  interviewer: '직접 입력',
}

export const STAGE_LABEL: Record<ApplicationStage, string> = {
  screening: '서류',
  interview_scheduled: '면접 예정',
  interviewing: '면접 중',
  interviewed: '평가 대기',
  evaluated: '평가 완료',
}

export const AI_SCORING_LABEL: Record<AiScoringStatus, string> = {
  not_started: '대기',
  running: '채점 중',
  completed: '완료',
  failed: '실패',
}

/** De-identification tokens such as [지원자], [학교-1], [회사-2], [전화-1]. */
export const DEID_TOKEN_RE = /\[[^[\]\s]{1,10}(?:-\d+)?\]/g

/** Split text into plain parts and de-identification tokens (for chip rendering). */
export function splitTokens(text: string): { text: string; token: boolean }[] {
  const out: { text: string; token: boolean }[] = []
  let last = 0
  for (const m of text.matchAll(DEID_TOKEN_RE)) {
    const i = m.index ?? 0
    if (i > last) out.push({ text: text.slice(last, i), token: false })
    out.push({ text: m[0], token: true })
    last = i + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), token: false })
  return out
}

/** Screening rationale lines: `+ ` strength, `- ` concern, anything else summary. */
export function parseRationale(rationale: string) {
  const summary: string[] = []
  const strengths: string[] = []
  const concerns: string[] = []
  for (const raw of rationale.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('+ ')) strengths.push(line.slice(2))
    else if (line.startsWith('- ')) concerns.push(line.slice(2))
    else summary.push(line)
  }
  return { summary: summary.join(' '), strengths, concerns }
}
