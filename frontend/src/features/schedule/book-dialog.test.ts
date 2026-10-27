import { screen, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import BookDialog from './BookDialog.vue'

const EVALUATING = '0a1b2c3d-0000-4000-9000-c20000000000' // CAND-0005 1차, 김서연 to submit

describe('면접 잡기: the round comes first (mock API)', { timeout: 30_000 }, () => {
  it('lists only who waits for the chosen round and says how many', async () => {
    const user = userEvent.setup()
    const db = getDb()
    // CAND-0005 passes 1차: every interviewer submitted, then a person decided.
    db.submittedAt.set(`${EVALUATING}:${db.me.id}`, new Date().toISOString())
    db.decide(EVALUATING, 'passed', '1차 합격', db.me.id)
    const [kim, park] = db.interviewers
    const suggestion = { start_at: '2027-01-05T05:00:00.000Z', end_at: '2027-01-05T06:00:00.000Z', interviewer_ids: [kim!.id, park!.id] }
    await renderRoute(BookDialog, { path: '/', url: '/', props: { suggestion, interviewers: db.interviewers } })

    expect(await screen.findByRole('radio', { name: /1차/ })).toHaveTextContent('2')
    const rounds = screen.getByTestId('book-round')
    expect(screen.getByTestId('book-guidance')).toHaveTextContent('서류 통과 2명 대기')
    await user.click(within(rounds).getByRole('radio', { name: /2차/ }))
    expect(screen.getByTestId('book-guidance')).toHaveTextContent('1차 합격 1명 대기')

    await user.click(screen.getByRole('combobox', { name: '지원자 선택' }))
    const options = await screen.findAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([expect.stringContaining('CAND-0005')])
    await user.click(options[0]!)
    expect(screen.getByRole('radio', { name: '대면', checked: true })).toBeInTheDocument() // 2차 default
    await user.click(screen.getByRole('button', { name: '일정 확정' }))

    const created = await new Promise<ReturnType<typeof db.sessions.at>>((resolve) => {
      const check = () => {
        const s = db.sessions.find((x) => x.application_id === db.session(EVALUATING)!.application_id && x.status === 'scheduled')
        if (s) resolve(s)
        else setTimeout(check, 20)
      }
      check()
    })
    expect(db.round(created!.round_id)!.label).toBe('2차')
    expect(created!.mode).toBe('onsite')
  })
})
