import type {
  ApplicationChannel,
  ApplicationStage,
  AiScoringStatus,
  IntakeEventType,
  IntakeStatus,
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

export const CHANNEL_LABEL: Record<ApplicationChannel, string> = {
  upload: '직접 업로드',
  site: '사이트 연동',
}

export const INTAKE_EVENT_LABEL: Record<IntakeEventType, string> = {
  submitted: '제출',
  updated: '수정',
  withdrawn: '철회',
}

export const INTAKE_STATUS_LABEL: Record<IntakeStatus, string> = {
  queued: '대기',
  processing: '처리 중',
  done: '반영',
  skipped: '건너뜀',
  failed: '실패',
  rejected: '거절',
}

/** Reason codes of docs/site-intake-spec.md (failed, rejected and skipped events). */
export const INTAKE_CODE_LABEL: Record<string, string> = {
  unknown_posting: '모르는 공고 번호',
  posting_closed: '마감된 공고',
  unsupported_attachment: '지원하지 않는 첨부 형식',
  unreadable_attachment: '읽을 수 없는 첨부',
  ocr_required: '스캔본 (OCR 필요)',
  ocr_unavailable: 'OCR로 읽지 못함',
  encrypted_attachment: '암호 걸린 첨부',
  converter_missing: '변환기 없음 (.doc·.ppt)',
  reader_unavailable: '읽기 도구를 쓸 수 없음',
  missing_field: '필수 칸 누락',
  invalid_field: '형식이 맞지 않는 칸',
  forbidden_field: '받지 않는 항목',
  duplicate_application: '같은 공고 중복 지원',
  application_withdrawn: '철회된 지원 번호',
  ai_failed: 'AI 선별 실패',
  internal_error: '처리 오류',
  stale_revision: '이미 더 새 버전',
  withdrawn: '철회로 취소',
}

export const intakeCodeLabel = (code: string) => INTAKE_CODE_LABEL[code] ?? code
