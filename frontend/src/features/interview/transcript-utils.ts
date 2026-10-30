import type { QAItem, TranscriptSegment } from '@/api/types'

export interface Turn {
  key: string
  speaker: 'interviewer' | 'candidate'
  qaId: string | null
  startMs: number
  parts: { id: string; text: string; final: boolean }[]
}

/** Group consecutive segments of the same speaker and question into turns. */
export function buildTurns(segments: readonly TranscriptSegment[], partial: TranscriptSegment | null): Turn[] {
  const all = partial ? [...segments, partial] : segments
  const turns: Turn[] = []
  for (const s of all) {
    const last = turns[turns.length - 1]
    if (last && last.speaker === s.speaker && last.qaId === s.qa_item_id) {
      last.parts.push({ id: s.segment_id, text: s.text, final: s.is_final })
    } else {
      turns.push({ key: s.segment_id, speaker: s.speaker, qaId: s.qa_item_id, startMs: s.start_ms, parts: [{ id: s.segment_id, text: s.text, final: s.is_final }] })
    }
  }
  return turns
}

export interface Block {
  key: string
  /** null: speech not tied to a recorded question (yet) */
  qa: QAItem | null
  /** a later stretch of a question already shown above (no second header) */
  continued: boolean
  turns: Turn[]
}

/**
 * The Q&A as one list: the turns grouped under their question, in order. A recorded question the transcript
 * has not heard (picked while the transcription was down, or a moment before its segment arrives) still
 * gets its place, by its number, so every question shows here and only here.
 */
export function buildBlocks(turns: readonly Turn[], qaItems: readonly QAItem[]): Block[] {
  const byId = new Map(qaItems.map((q) => [q.id, q]))
  const blocks: Block[] = []
  const seen = new Set<string>()
  for (const t of turns) {
    const qa = (t.qaId && byId.get(t.qaId)) || null
    const last = blocks[blocks.length - 1]
    if (last && last.qa?.id === qa?.id) {
      last.turns.push(t)
      continue
    }
    blocks.push({ key: t.key, qa, continued: qa !== null && seen.has(qa.id), turns: [t] })
    if (qa) seen.add(qa.id)
  }
  for (const qa of [...qaItems].sort((a, b) => a.seq - b.seq)) {
    if (seen.has(qa.id)) continue
    const later = blocks.findIndex((b) => b.qa !== null && b.qa.seq > qa.seq)
    blocks.splice(later === -1 ? blocks.length : later, 0, { key: `qa-${qa.id}`, qa, continued: false, turns: [] })
  }
  return blocks
}

/** Enter submits, Shift+Enter breaks the line; never submit mid-IME composition (Korean input). */
export function submitOnEnter(e: KeyboardEvent, submit: () => void) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault()
    submit()
  }
}

/** Esc leaves the box (text kept), so the room's number keys work again. */
export function blurOnEscape(e: KeyboardEvent) {
  if (e.key === 'Escape' && !e.isComposing && e.target instanceof HTMLElement) {
    e.preventDefault()
    e.target.blur()
  }
}

/** Ctrl/⌘+Enter submits (multi-line notes and manual answers); ignored mid-IME composition. */
export function submitOnModEnter(e: KeyboardEvent, submit: () => void) {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}
