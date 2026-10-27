import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { getDb, roundIdOf } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import LiveInterviewPage from './LiveInterviewPage.vue'

const LIVE2 = '0a1b2c3d-0000-4000-9000-live20000000' // P1 2차 임원 면접 in progress (CAND-0009)
const P1 = 'b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0001'
const WAIT = { timeout: 15_000, interval: 100 }

const open = () => renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: `/sessions/${LIVE2}/live` })

describe('2차 interview: what it sees of 1차 (mock API)', { timeout: 60_000 }, () => {
  it('shows the round in the header and the 1차 summary with scores hidden by the posting setting', async () => {
    await open()
    const summary = (await screen.findAllByTestId('previous-round'))[0]!
    expect(within(summary).getByText('1차 직무 면접 요약')).toBeInTheDocument()
    expect(within(summary).getByTestId('scores-hidden')).toHaveTextContent('1차 점수 숨김 (공고 설정)')
    expect(within(summary).queryByTestId('scores-visible')).toBeNull()
    expect(within(summary).getByText(/확인이 필요한 점 3/)).toBeInTheDocument()
    expect(within(summary).getAllByText(/메모 1개/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('임원 면접').length).toBeGreaterThan(0) // "2차 · 임원 면접" badge
  })

  it('shows 1차 scores, apart and never summed, once the round allows it', async () => {
    getDb().round(roundIdOf(P1, 2))!.show_previous_scores = true
    await open()
    const summary = (await screen.findAllByTestId('previous-round'))[0]!
    const table = within(summary).getByTestId('scores-visible')
    expect(within(table).getByText('면접관')).toBeInTheDocument()
    expect(within(table).getByText('AI 참고')).toBeInTheDocument()
    expect(within(summary).queryByTestId('scores-hidden')).toBeNull()
    expect(within(summary).getByText(/결정 사유/)).toBeInTheDocument()
  })

  it('drafts carry-over questions from 1차 answers that do not repeat 1차 questions, and asks one', async () => {
    const user = userEvent.setup()
    await open()
    const section = (await screen.findAllByTestId('carryover'))[0]!
    await user.click(within(section).getByRole('button', { name: '만들기' }))
    await waitFor(() => expect(within(section).getAllByRole('button', { name: /이어 질문 기록/ }).length).toBeGreaterThan(0), WAIT)
    const db = getDb()
    const carried = db.carryover.get(LIVE2)!
    const earlier = db.earlierSessions(LIVE2).flatMap((s) => db.qaOf(s.id))
    for (const q of carried) {
      expect(q.origin?.round.label).toBe('1차')
      expect(earlier.some((e) => e.answer_deidentified?.includes(q.origin!.grounding))).toBe(true)
      expect(earlier.map((e) => e.question)).not.toContain(q.question)
    }
    await user.click(within(section).getAllByRole('button', { name: /이어 질문 기록/ })[0]!)
    await waitFor(() => expect(db.qaOf(LIVE2).at(-1)?.question).toBe(carried[0]!.question), WAIT)
    expect(db.qaOf(LIVE2).at(-1)?.question_source).toBe('preset')
  })
})
