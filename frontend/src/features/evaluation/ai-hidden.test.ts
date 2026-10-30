import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import EvaluationPage from './EvaluationPage.vue'

// jsdom has no canvas for Chart.js; the table shows the same numbers.
vi.mock('./ScoreChart.vue', () => ({ default: { render: () => null } }))

const EVALUATING = '0a1b2c3d-0000-4000-9000-c20000000000' // 1차, AI scored, 김서연 (signed in) has not submitted
const OTHER_PANEL = '0a1b2c3d-0000-4000-9000-r1n120000000' // a panel without 김서연

const open = (id: string) => renderRoute(EvaluationPage, { path: '/sessions/:sessionId/evaluation', url: `/sessions/${id}/evaluation` })

async function tableView() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('radio', { name: '표' }))
}

describe('AI 점수는 내 점수를 제출한 뒤에 (mock API)', { timeout: 30_000 }, () => {
  it('hides AI scores and evidence from an interviewer who has not submitted', async () => {
    await open(EVALUATING)
    const hidden = await screen.findByTestId('ai-hidden')
    expect(hidden).toHaveTextContent('내 점수를 먼저 제출하세요')
    await tableView()
    expect(screen.queryAllByTestId('ai-score')).toHaveLength(0)
    expect(screen.queryByText(/답변 \d+개/)).toBeNull() // no per-competency AI summary
    expect(screen.queryByLabelText('AI 점수 가리기')).toBeNull()
  })

  it('그래도 보기 asks first, then shows them and records it in the audit log', async () => {
    const user = userEvent.setup()
    await open(EVALUATING)
    const hidden = await screen.findByTestId('ai-hidden')
    await user.click(within(hidden).getByRole('button', { name: '그래도 보기' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(confirm).toHaveTextContent('감사 로그에 남고')
    await user.click(within(confirm).getByRole('button', { name: '그래도 보기' }))

    await waitFor(() => expect(screen.queryByTestId('ai-hidden')).toBeNull())
    await tableView()
    expect(screen.getAllByTestId('ai-score').length).toBeGreaterThan(0)
    const db = getDb()
    const entry = db.audit.find((a) => a.action === 'evaluation.ai_revealed')
    expect(entry).toMatchObject({ target_id: EVALUATING, actor_id: db.me.id })
  })

  it('shows them once the interviewer has submitted, with no reveal recorded', async () => {
    const db = getDb()
    db.submittedAt.set(`${EVALUATING}:${db.me.id}`, new Date().toISOString())
    await open(EVALUATING)
    await screen.findByTestId('decision-panel')
    expect(screen.queryByTestId('ai-hidden')).toBeNull()
    await tableView()
    expect(screen.getAllByTestId('ai-score').length).toBeGreaterThan(0)
    expect(db.audit.some((a) => a.action === 'evaluation.ai_revealed')).toBe(false)
  })

  it('shows them to someone who is not on the panel (nothing of theirs to anchor)', async () => {
    await open(OTHER_PANEL)
    await screen.findByTestId('decision-panel')
    expect(screen.queryByTestId('ai-hidden')).toBeNull()
  })
})
