/**
 * Mock real-time engine. Simulates what the backend (STT + LLM) will push:
 *  - transcript: the interviewer's question as a final segment, then the candidate's scripted
 *    answer as sentence segments that grow character by character (partial -> final), then
 *    `qa.answered`.
 *  - follow-ups: 2-3 suggestions streamed token by token for a given QA item.
 */
import type { FollowUpEvent, QAItem, StreamStatus, TranscriptEvent, TranscriptSegment } from '@/api/types'

import { GENERIC_BANK } from './data/banks'
import { FOLLOWUP_PROMPT, AI_MODEL, getDb, newId, splitSentences, type MockDb } from './db'

/** Timing multiplier: 1 = demo speed, tests set it close to 0. */
export const mockConfig = { speed: 1 }

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms * mockConfig.speed))

type Listener = (e: TranscriptEvent) => void

interface LiveState {
  listeners: Set<Listener>
  streamingQa: string | null
  /** bumped to cancel the answer currently streaming */
  run: number
  statusTimer: ReturnType<typeof setInterval> | null
}

const states = new Map<string, LiveState>()

function state(sessionId: string): LiveState {
  let s = states.get(sessionId)
  if (!s) {
    s = { listeners: new Set(), streamingQa: null, run: 0, statusTimer: null }
    states.set(sessionId, s)
  }
  return s
}

function emit(sessionId: string, e: TranscriptEvent) {
  for (const l of state(sessionId).listeners) l(e)
}

export function currentStatus(db: MockDb, sessionId: string): StreamStatus {
  const session = db.session(sessionId)
  if (!session || session.status !== 'in_progress') return { recording: 'stopped', stt: 'off', latency_ms: null }
  if (!session.has_recording) return { recording: 'off', stt: 'off', latency_ms: null }
  return { recording: 'recording', stt: 'ok', latency_ms: 260 + Math.round(Math.random() * 220) }
}

function sessionElapsedMs(db: MockDb, sessionId: string) {
  const started = db.session(sessionId)?.started_at
  return started ? Date.now() - new Date(started).getTime() : 0
}

function pushSegment(db: MockDb, sessionId: string, seg: TranscriptSegment) {
  const list = db.transcripts.get(sessionId) ?? []
  list.push(seg)
  db.transcripts.set(sessionId, list)
}

/** Subscribe to a session's transcript stream. Returns an unsubscribe function. */
export function subscribe(sessionId: string, listener: Listener): () => void {
  const db = getDb()
  const st = state(sessionId)
  st.listeners.add(listener)
  listener({ event: 'status', data: currentStatus(db, sessionId) })
  if (!st.statusTimer) {
    st.statusTimer = setInterval(() => emit(sessionId, { event: 'status', data: currentStatus(getDb(), sessionId) }), 5000)
  }
  // A question that was asked but not answered yet (e.g. page reload mid-answer): start answering.
  const session = db.session(sessionId)
  if (session?.status === 'in_progress' && session.has_recording && !st.streamingQa) {
    const pending = db.qaOf(sessionId).find((q) => q.asked_at && !q.answered_at)
    if (pending) void streamAnswer(sessionId, pending, 600)
  }
  return () => {
    st.listeners.delete(listener)
    if (st.listeners.size === 0 && st.statusTimer) {
      clearInterval(st.statusTimer)
      st.statusTimer = null
    }
  }
}

/** Called when the interviewer records a question. In recording mode the candidate "answers". */
export function onQuestionAsked(sessionId: string, qa: QAItem) {
  const db = getDb()
  const session = db.session(sessionId)
  if (!session || session.status !== 'in_progress' || !session.has_recording) return
  void (async () => {
    await wait(250)
    const start = sessionElapsedMs(db, sessionId)
    const seg: TranscriptSegment = {
      segment_id: newId(),
      qa_item_id: qa.id,
      speaker: 'interviewer',
      text: qa.question,
      is_final: true,
      start_ms: start,
      end_ms: start + qa.question.length * 110,
    }
    pushSegment(db, sessionId, seg)
    emit(sessionId, { event: 'segment.final', data: seg })
    await streamAnswer(sessionId, qa, 900)
  })()
}

async function streamAnswer(sessionId: string, qa: QAItem, delayMs: number) {
  const db = getDb()
  const st = state(sessionId)
  if (st.streamingQa === qa.id) return
  st.streamingQa = qa.id
  const run = ++st.run
  const stale = () => st.run !== run
  const answer = db.qaMeta.get(qa.id)?.answer ?? db.nextGenericAnswer('P1')
  await wait(delayMs)
  for (const sentence of splitSentences(answer)) {
    const segment_id = newId()
    const start_ms = sessionElapsedMs(db, sessionId)
    let i = 0
    while (i < sentence.length) {
      if (stale()) return
      i = Math.min(sentence.length, i + 1 + (Math.random() < 0.35 ? 1 : 0))
      emit(sessionId, {
        event: 'segment.partial',
        data: { segment_id, qa_item_id: qa.id, speaker: 'candidate', text: sentence.slice(0, i), is_final: false, start_ms, end_ms: null },
      })
      await wait(42)
    }
    const seg: TranscriptSegment = { segment_id, qa_item_id: qa.id, speaker: 'candidate', text: sentence, is_final: true, start_ms, end_ms: sessionElapsedMs(db, sessionId) }
    pushSegment(db, sessionId, seg)
    emit(sessionId, { event: 'segment.final', data: seg })
    await wait(380)
  }
  if (stale()) return
  const item = db.qaItems.find((q) => q.id === qa.id)
  if (item) {
    item.answer_deidentified = answer
    item.answered_at = new Date().toISOString()
    emit(sessionId, { event: 'qa.answered', data: { qa_item_id: item.id, answer_deidentified: answer, answered_at: item.answered_at } })
  }
  st.streamingQa = null
}

/** Stop any running answer (session ended, or a new question interrupts). */
export function stopStreaming(sessionId: string) {
  const st = state(sessionId)
  st.run += 1
  st.streamingQa = null
  emit(sessionId, { event: 'status', data: currentStatus(getDb(), sessionId) })
}

/** Drop all live state (tests reset the mock DB between cases). */
export function resetLive() {
  for (const st of states.values()) {
    st.run += 1
    st.streamingQa = null
    st.listeners.clear()
    if (st.statusTimer) clearInterval(st.statusTimer)
  }
  states.clear()
}

/** Stream 3 follow-up suggestions for a QA item. */
export async function* followUps(sessionId: string, qaItemId: string): AsyncGenerator<FollowUpEvent> {
  const db = getDb()
  const qa = db.qaItems.find((q) => q.id === qaItemId && q.session_id === sessionId)
  if (!qa || !qa.answer_deidentified) {
    yield { event: 'error', data: { message: '답변이 아직 없어 꼬리질문을 만들 수 없습니다.' } }
    return
  }
  const meta = db.qaMeta.get(qa.id)
  const postingKey = meta?.postingKey ?? 'P1'
  let seeds = meta?.suggestions ?? null
  if (!seeds || seeds.length === 0) seeds = GENERIC_BANK[postingKey]!.suggestions
  // Generic suggestions rotate so repeated requests differ a little.
  if (seeds === GENERIC_BANK[postingKey]!.suggestions) {
    const n = db.genericCursor.get(`s:${postingKey}`) ?? 0
    db.genericCursor.set(`s:${postingKey}`, n + 1)
    seeds = [...seeds.slice(n % seeds.length), ...seeds.slice(0, n % seeds.length)]
  }
  const firstSentence = splitSentences(qa.answer_deidentified)[0] ?? qa.answer_deidentified
  const batch_id = newId()
  db.log({ actor_type: 'ai', action: 'followup.generated', target_type: 'interview_session', target_id: sessionId, model: AI_MODEL, prompt_version: FOLLOWUP_PROMPT, details: { qa_item_id: qa.id } })
  yield { event: 'batch.start', data: { batch_id, qa_item_id: qa.id, model: AI_MODEL, prompt_version: FOLLOWUP_PROMPT } }
  await wait(550)
  for (const [index, seedItem] of seeds.slice(0, 3).entries()) {
    const suggestion_id = newId()
    const grounding = seedItem.grounding && qa.answer_deidentified.includes(seedItem.grounding) ? seedItem.grounding : firstSentence
    db.suggestions.set(suggestion_id, { ...seedItem, grounding, batch_id, suggestion_id, qa_item_id: qa.id })
    yield { event: 'suggestion.start', data: { batch_id, suggestion_id, index, competency: seedItem.competency } }
    const text = seedItem.question
    let i = 0
    while (i < text.length) {
      const step = 2 + Math.floor(Math.random() * 3)
      yield { event: 'suggestion.delta', data: { batch_id, suggestion_id, text: text.slice(i, i + step) } }
      i += step
      await wait(24)
    }
    yield {
      event: 'suggestion.done',
      data: { batch_id, suggestion_id, index, competency: seedItem.competency, question: text, rationale: seedItem.rationale, grounding },
    }
    await wait(160)
  }
  yield { event: 'batch.done', data: { batch_id } }
}
