import type { TranscriptSegment } from '@/api/types'

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

/** Enter submits, Shift+Enter breaks the line; never submit mid-IME composition (Korean input). */
export function submitOnEnter(e: KeyboardEvent, submit: () => void) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault()
    submit()
  }
}

/** Ctrl/⌘+Enter submits (multi-line notes and manual answers); ignored mid-IME composition. */
export function submitOnModEnter(e: KeyboardEvent, submit: () => void) {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}
