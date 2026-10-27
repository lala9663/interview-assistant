import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import EvaluationPage from './EvaluationPage.vue'

// jsdom has no canvas for Chart.js; the chart is not what these tests are about.
vi.mock('./ScoreChart.vue', () => ({ default: { render: () => null } }))

const EVALUATING = '0a1b2c3d-0000-4000-9000-c20000000000' // 1차, 김서연 has not submitted
const ROUND2_DONE = '0a1b2c3d-0000-4000-9000-r2n100000000' // 2차 (last round), both submitted

const open = (id: string) => renderRoute(EvaluationPage, { path: '/sessions/:sessionId/evaluation', url: `/sessions/${id}/evaluation` })

describe('N차 결정 (mock API)', { timeout: 30_000 }, () => {
  it('waits until every interviewer submitted, and says what a pass opens', async () => {
    await open(EVALUATING)
    const panel = await screen.findByTestId('decision-panel')
    expect(within(panel).getByRole('heading', { name: /1차 결정/ })).toBeInTheDocument()
    expect(within(panel).getByTestId('decision-blocked')).toHaveTextContent('면접관 점수가 모두 제출된 뒤에 결정할 수 있습니다.')
    expect(within(panel).getByText(/합격하면 2차 임원 면접 대상이 됩니다/)).toBeInTheDocument()
    expect(within(panel).getByText(/AI 점수는 참고용/)).toBeInTheDocument()
    expect(screen.getAllByTestId('round-badge')[0]).toHaveTextContent('1차·직무 면접')
  })

  it('records a reasoned decision in the last round: a final candidate, recorded officially on the site', async () => {
    const user = userEvent.setup()
    await open(ROUND2_DONE)
    const panel = await screen.findByTestId('decision-panel')
    expect(within(panel).getByTestId('final-notice')).toHaveTextContent('합격하면 최종 합격 후보가 됩니다. 공식 결과는 채용 사이트에 기록합니다')

    const submit = within(panel).getByRole('button', { name: '2차 결정 기록' })
    await user.click(within(panel).getByRole('radio', { name: '합격' }))
    expect(submit).toBeDisabled() // a reason is required
    await user.type(within(panel).getByLabelText(/사유/), '책임감과 영향력 근거가 분명함')
    await user.click(submit)

    const history = await within(panel).findByTestId('decision-history')
    expect(history).toHaveTextContent('합격')
    expect(history).toHaveTextContent('책임감과 영향력 근거가 분명함')
    const db = getDb()
    const s = db.session(ROUND2_DONE)!
    expect(db.currentDecision(s.application_id, s.round_id)).toMatchObject({ decision: 'passed', revision: 1 })
    expect(db.stage(s.application_id)).toMatchObject({ kind: 'final', status: 'passed' })

    // Changing it keeps the history: a new revision on top.
    await user.click(within(panel).getByRole('radio', { name: '보류' }))
    await user.type(within(panel).getByLabelText(/사유/), '다른 후보와 비교 후 다시 결정')
    await user.click(within(panel).getByRole('button', { name: '결정 바꾸기' }))
    await waitFor(() => expect(within(within(panel).getByTestId('decision-history')).getAllByRole('listitem')).toHaveLength(2))
    expect(db.decisionHistory(s.application_id, s.round_id).map((d) => [d.revision, d.decision])).toEqual([
      [2, 'hold'],
      [1, 'passed'],
    ])
    expect(db.audit.find((a) => a.action === 'round.decision_changed')?.details).toMatchObject({ from: 'passed', to: 'hold' })
  })

  it('takes points to check for the next round, and shows the AI ones with their evidence', async () => {
    const user = userEvent.setup()
    const C1 = '0a1b2c3d-0000-4000-9000-c10000000000' // 1차 with AI points
    await open(C1)
    const card = await screen.findByTestId('check-points')
    expect(within(card).getByRole('heading', { name: '2차에서 확인할 점' })).toBeInTheDocument()
    expect(within(card).getAllByText(/AI · 참고/).length).toBeGreaterThan(0)
    await user.type(within(card).getByRole('textbox', { name: '확인할 점' }), '리더 경험의 범위를 구체적으로')
    await user.click(within(card).getByRole('button', { name: '남기기' }))
    expect(await within(card).findByText('리더 경험의 범위를 구체적으로')).toBeInTheDocument()
  })
})
