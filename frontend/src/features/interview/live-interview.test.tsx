import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import LiveInterviewPage from './live-interview-page'

const LIVE = '0a1b2c3d-0000-4000-9000-live00000000'
const SCHEDULED = '0a1b2c3d-0000-4000-9000-s10000000000'

/** Three finished suggestion cards (text query: role queries are slow while the transcript streams). */
async function suggestionsReady() {
  await waitFor(() => expect(screen.getAllByText('이 질문 사용')).toHaveLength(3), { timeout: 12_000, interval: 100 })
}

function qaLog() {
  return screen.getByRole('list', { name: 'Q&A 기록' })
}

describe('live interview (mock API over MSW)', { timeout: 20_000 }, () => {
  it('streams the answer, suggests follow-ups without asking them, and records the chosen one as a Q&A item', async () => {
    const user = userEvent.setup()
    renderRoute(<LiveInterviewPage />, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE}/live` })

    // Q1-Q3 already recorded; Q3's answer streams in, then three suggestions arrive.
    await suggestionsReady()
    expect(screen.getByText(/자동으로 묻지 않으며/)).toBeInTheDocument()
    expect(within(qaLog()).getAllByRole('listitem')).toHaveLength(3)
    expect(getDb().qaOf(LIVE)).toHaveLength(3)

    const first = screen.getAllByRole('listitem', { name: /꼬리질문 후보/ })[0]!
    const question = within(first).getByText(/히터 온도 때문이라고 확정하기 전에/).textContent!
    await user.click(within(first).getByRole('button', { name: '이 질문 사용' }))

    await waitFor(() => expect(within(qaLog()).getAllByRole('listitem')).toHaveLength(4))
    const q4 = within(qaLog()).getAllByRole('listitem')[3]!
    expect(q4).toHaveTextContent('Q4')
    expect(q4).toHaveTextContent('AI 제안')
    expect(q4).toHaveTextContent(question)
    expect(within(first).getByText(/기록됨 · Q4/)).toBeInTheDocument()

    const stored = getDb().qaOf(LIVE)[3]!
    expect(stored).toMatchObject({ seq: 4, question_source: 'ai_suggested', question })
  })

  it('edited suggestions are recorded with the edited text', async () => {
    const user = userEvent.setup()
    renderRoute(<LiveInterviewPage />, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE}/live` })
    await suggestionsReady()
    const second = screen.getAllByRole('listitem', { name: /꼬리질문 후보/ })[1]!
    await user.click(within(second).getByRole('button', { name: /수정 후 사용/ }))
    const box = within(second).getByRole('textbox', { name: '꼬리질문 수정' })
    await user.clear(box)
    await user.type(box, '그 기준을 팀에 어떻게 공유했나요?')
    await user.click(within(second).getByRole('button', { name: '수정한 질문 사용' }))

    await waitFor(() => expect(getDb().qaOf(LIVE)).toHaveLength(4))
    expect(getDb().qaOf(LIVE)[3]).toMatchObject({ question: '그 기준을 팀에 어떻게 공유했나요?', question_source: 'ai_suggested' })
    expect(await within(qaLog()).findByText('수정함')).toBeInTheDocument()
  })

  it('requires the recording consent step before starting', async () => {
    const user = userEvent.setup()
    renderRoute(<LiveInterviewPage />, { path: '/sessions/:sessionId/live', url: `/sessions/${SCHEDULED}/live` })
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
