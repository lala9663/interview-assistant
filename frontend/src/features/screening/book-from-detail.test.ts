import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { endpoints } from '@/api/endpoints'
import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import ApplicationSheet from './ApplicationSheet.vue'

const applicationOf = (n: number) => `d1e2f3a4-0000-4000-9000-${String(n).padStart(12, '0')}`
const EVALUATING = '0a1b2c3d-0000-4000-9000-c20000000000' // CAND-0005 1차, 김서연 to submit

/** The detail sheet of CAND-000n, loaded. */
async function openSheet(n: number) {
  const id = applicationOf(n)
  await renderRoute(ApplicationSheet, { path: '/', url: '/', props: { applicationId: id, postingId: getDb().application(id)!.posting_id } })
  await screen.findByRole('heading', { name: '면접' })
}

describe('면접 잡기 from 지원자 상세 (mock API)', { timeout: 30_000 }, () => {
  it('shows the action only to someone waiting for their next round', async () => {
    await openSheet(2) // 서류 통과, no 1차 yet
    const row = await screen.findByTestId('next-round')
    expect(within(row).getByTestId('round-badge')).toHaveTextContent('1차')
    expect(within(row).getByTestId('status-chip')).toHaveTextContent('일정 대기')
    expect(within(row).getByRole('button', { name: '면접 잡기' })).toBeInTheDocument()
  })

  it.each([
    [6, '서류 보류'],
    [4, '서류 탈락'],
    [11, '1차 예정'],
    [14, '1차 보류'],
    [12, '최종 합격 후보'],
  ])('shows nothing for CAND-%i (%s)', async (n) => {
    await openSheet(n)
    expect(screen.queryByTestId('next-round')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '면접 잡기' })).not.toBeInTheDocument()
  })

  it('offers 1차 once the screening is passed in the sheet', async () => {
    const user = userEvent.setup()
    await openSheet(6)
    expect(screen.getByText(/서류 통과 처리 후 여기서 1차 일정을/)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: '통과' }))
    expect(await screen.findByRole('button', { name: '면접 잡기' })).toBeInTheDocument()
  })

  it('offers 2차 after a 1차 pass, with the round default mode', async () => {
    const user = userEvent.setup()
    const db = getDb()
    db.submittedAt.set(`${EVALUATING}:${db.me.id}`, new Date().toISOString())
    db.decide(EVALUATING, 'passed', '1차 합격', db.me.id)
    await openSheet(5)
    const row = await screen.findByTestId('next-round')
    expect(within(row).getByTestId('round-badge')).toHaveTextContent('2차')
    expect(row).toHaveTextContent('대면')

    await user.click(within(row).getByRole('button', { name: '면접 잡기' }))
    const dialog = await screen.findByRole('dialog', { name: '면접 잡기' })
    expect(within(within(dialog).getByTestId('book-fixed')).getByTestId('round-badge')).toHaveTextContent(/2차.*임원 면접/)
    expect(within(dialog).getByRole('radio', { name: '대면', checked: true })).toBeInTheDocument()
  })

  it('books the fixed round from the suggested common free slots', async () => {
    const user = userEvent.setup()
    const db = getDb()
    const [kim, park] = db.interviewers
    await openSheet(2)
    await user.click(await screen.findByRole('button', { name: '면접 잡기' }))

    const dialog = await screen.findByRole('dialog', { name: '면접 잡기' })
    const fixed = within(dialog).getByTestId('book-fixed')
    expect(fixed).toHaveTextContent('CAND-0002')
    expect(within(fixed).getByTestId('round-badge')).toHaveTextContent(/1차.*직무 면접/)
    // The round recommends 2: the posting's job family (공정개발) comes first.
    expect(await within(dialog).findByRole('checkbox', { name: `${kim!.name} 선택` })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: `${park!.name} 선택` })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: '이하은 선택' })).not.toBeChecked()
    expect(within(dialog).getByTestId('book-panel-count')).toHaveTextContent('2명 · 권장 2명')
    const confirm = within(dialog).getByRole('button', { name: '일정 확정' })
    expect(confirm).toBeDisabled()

    const slots = await within(dialog).findByRole('radiogroup', { name: '함께 비는 시간' })
    const first = within(slots).getAllByRole('radio')[0]!
    await user.click(first)
    expect(first).toHaveAttribute('aria-checked', 'true')
    expect(within(dialog).getByRole('radio', { name: '비대면', checked: true })).toBeInTheDocument() // 1차 default
    expect(within(dialog).getByRole('combobox', { name: '주관 면접관' })).toHaveTextContent(kim!.name)
    await user.click(confirm)

    // The sheet's 면접 section shows the new session, and the action is gone.
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '면접 잡기' })).not.toBeInTheDocument())
    const link = await screen.findByRole('link', { name: /1차.*예정/ })
    expect(screen.queryByTestId('next-round')).not.toBeInTheDocument()

    const created = db.sessions.find((s) => s.application_id === applicationOf(2))!
    expect(link).toHaveAttribute('href', `/sessions/${created.id}/live`)
    expect(db.round(created.round_id)!.label).toBe('1차')
    expect(created.mode).toBe('remote')
    expect(db.panelOf(created.id).map((p) => [p.interviewer_id, p.role])).toEqual([
      [kim!.id, 'lead'],
      [park!.id, 'panel'],
    ])

    // The booked hour is no longer a common free slot for that panel.
    const now = new Date()
    const again = await endpoints.scheduleSuggestions({
      interviewer_ids: [kim!.id, park!.id],
      from: now.toISOString(),
      to: new Date(now.getTime() + 14 * 86_400_000).toISOString(),
      duration_minutes: 60,
    })
    expect(again.map((s) => s.start_at)).not.toContain(created.scheduled_at)
  })
})
