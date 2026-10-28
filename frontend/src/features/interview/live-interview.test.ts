import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import LiveInterviewPage from './LiveInterviewPage.vue'

const LIVE = '0a1b2c3d-0000-4000-9000-live00000000'
const SCHEDULED = '0a1b2c3d-0000-4000-9000-s10000000000'

const WAIT = { timeout: 15_000, interval: 100 }

/** Three finished AI cards, usable (past their duplicate check; the question-bank cards come first, finished at once). waitFor reruns its
 * check on every DOM change, and the transcript and the suggestions stream hundreds of them: a whole-page
 * text query each time made this wait CPU-bound, and under load it timed out with two cards of three. So it
 * watches the suggestions panel only, with a plain selector, and allows for a busy machine. */
async function suggestionsReady() {
  let panel: HTMLElement | null = null
  await waitFor(() => expect((panel = document.querySelector<HTMLElement>('section[aria-label="꼬리질문 제안"]'))).not.toBeNull(), WAIT)
  const ready = () =>
    [...panel!.querySelectorAll<HTMLButtonElement>('li[data-source="ai"] button')].filter((b) => b.textContent?.trim() === '이 질문 사용' && !b.disabled)
  await waitFor(() => expect(ready()).toHaveLength(3), { ...WAIT, timeout: 40_000, container: panel! })
}

const aiCards = () => screen.getAllByRole('listitem', { name: /꼬리질문 후보 \d+ \(AI 생성\)/ })

function qaLog() {
  return screen.getByRole('list', { name: 'Q&A 기록' })
}

describe('live interview (mock API over MSW)', { timeout: 60_000 }, () => {
  it('streams the answer, suggests follow-ups without asking them, and records the chosen one as a Q&A item', async () => {
    const user = userEvent.setup()
    await renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE}/live` })

    // Q1-Q3 already recorded; Q3's answer streams in, then three suggestions arrive.
    await suggestionsReady()
    expect(screen.getByText(/자동으로 묻지 않으며/)).toBeInTheDocument()
    expect(within(qaLog()).getAllByRole('listitem')).toHaveLength(3)
    expect(getDb().qaOf(LIVE)).toHaveLength(3)

    // Approved question-bank questions close to the answer come first, marked as such.
    const cards = screen.getAllByRole('listitem', { name: /꼬리질문 후보/ })
    const sources = cards.map((c) => c.dataset.source)
    expect(sources[0]).toBe('bank')
    expect(sources.indexOf('ai')).toBeGreaterThan(sources.lastIndexOf('bank'))
    expect(within(cards[0]!).getByTestId('suggestion-source')).toHaveTextContent('질문 은행')

    const first = aiCards()[0]!
    expect(within(first).getByTestId('suggestion-source')).toHaveTextContent('AI 생성')
    const question = within(first).getByText(/히터 온도 때문이라고 확정하기 전에/).textContent!
    await user.click(within(first).getByRole('button', { name: '이 질문 사용' }))

    await waitFor(() => expect(within(qaLog()).getAllByRole('listitem')).toHaveLength(4), WAIT)
    const q4 = within(qaLog()).getAllByRole('listitem')[3]!
    expect(q4).toHaveTextContent('Q4')
    expect(q4).toHaveTextContent('꼬리질문 후보')
    expect(q4).toHaveTextContent(question)
    expect(within(first).getByText(/기록됨 · Q4/)).toBeInTheDocument()

    const stored = getDb().qaOf(LIVE)[3]!
    expect(stored).toMatchObject({ seq: 4, question_source: 'ai_suggested', question })
  })

  it('edited suggestions are recorded with the edited text', async () => {
    const user = userEvent.setup()
    await renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE}/live` })
    await suggestionsReady()
    const second = aiCards()[1]!
    await user.click(within(second).getByRole('button', { name: /수정 후 사용/ }))
    const box = within(second).getByRole('textbox', { name: '꼬리질문 수정' })
    await user.clear(box)
    await user.type(box, '그 기준을 팀에 어떻게 공유했나요?')
    await user.click(within(second).getByRole('button', { name: '수정한 질문 사용' }))

    await waitFor(() => expect(getDb().qaOf(LIVE)).toHaveLength(4), WAIT)
    expect(getDb().qaOf(LIVE)[3]).toMatchObject({ question: '그 기준을 팀에 어떻게 공유했나요?', question_source: 'ai_suggested' })
    expect(await within(qaLog()).findByText('수정함', {}, WAIT)).toBeInTheDocument()
  })

  it('folds an AI suggestion that turns out to repeat a question already asked, and never records it', async () => {
    const db = getDb()
    const [q1, , q3] = db.qaOf(LIVE)
    const repeated = db.qaMeta.get(q3!.id)!.suggestions![0]!.question
    q1!.question = repeated
    const user = userEvent.setup()
    await renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE}/live` })

    // Shown while it streamed, then dimmed and folded to one line once the check found the repeat.
    const folded = await screen.findByRole('listitem', { name: '꼬리질문 후보 (이미 한 질문과 비슷해 접음)' }, { ...WAIT, timeout: 40_000 })
    expect(folded).toHaveTextContent('이미 한 질문과 비슷함')
    expect(folded).toHaveTextContent(repeated)
    expect(within(folded).queryByRole('button', { name: '이 질문 사용' })).toBeNull()
    expect([...db.suggestions.values()].some((s) => s.question === repeated)).toBe(false) // not usable at all
    await waitFor(() => expect(screen.getByTestId('discarded-note')).toHaveTextContent('1개는 접었습니다'), WAIT)
    // The cards still offered are numbered without a gap; the folded one has no number.
    const numbers = screen.getAllByRole('listitem', { name: /꼬리질문 후보 \d+/ }).map((c) => Number(/후보 (\d+)/.exec(c.getAttribute('aria-label')!)![1]))
    expect(numbers).toEqual(numbers.map((_, i) => i + 1))

    await user.click(within(folded).getByRole('button', { name: '접은 후보 보기' }))
    const opened = screen.getByRole('listitem', { name: '꼬리질문 후보 (이미 한 질문과 비슷함)' })
    expect(opened).toHaveTextContent(`이미 한 질문과 뜻이 같아 쓰지 않습니다. 한 질문: ${repeated}`)
    expect(within(opened).queryByRole('button', { name: '이 질문 사용' })).toBeNull()
  })

  it('requires the recording consent step before starting', async () => {
    const user = userEvent.setup()
    await renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: `/sessions/${SCHEDULED}/live` })
    const start = await screen.findByRole('button', { name: '면접 시작' })
    expect(start).toBeDisabled()

    await user.click(screen.getByRole('radio', { name: /동의하지 않음/ }))
    await user.click(screen.getByRole('button', { name: '동의 여부 기록' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '면접 시작' })).toBeEnabled())
    expect(screen.getByText(/시작하면 녹음 없이 수기 모드로/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '면접 시작' }))
    expect(await screen.findByText(/수기 모드 · 녹음 안 함/)).toBeInTheDocument()
    expect(getDb().session(SCHEDULED)).toMatchObject({ status: 'in_progress', has_recording: false })
  })
})
