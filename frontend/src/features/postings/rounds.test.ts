import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import PostingDetailPage from './PostingDetailPage.vue'

const P2 = 'b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002'

describe('전형 tab (mock API)', { timeout: 30_000 }, () => {
  it('lists the rounds in order, adds one, and drafts its questions without repeating 1차', async () => {
    const user = userEvent.setup()
    await renderRoute(PostingDetailPage, { path: '/postings/:postingId', url: `/postings/${P2}` })
    const order = await screen.findByRole('list', { name: '차수 순서' })
    expect(within(order).getAllByRole('listitem')).toHaveLength(1)
    expect(within(order).getByLabelText('면접이 있어 순서 고정')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '차수 추가' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('차수 이름'), '기술 리더 면접')
    await user.click(within(dialog).getByRole('button', { name: '추가' }))
    await waitFor(() => expect(within(order).getAllByRole('listitem')).toHaveLength(2))
    expect(within(order).getAllByTestId('round-badge').map((b) => b.textContent?.trim())).toEqual(['1차', '2차'])
    const db = getDb()
    expect(db.roundsOf(P2).map((r) => [r.label, r.name])).toEqual([
      ['1차', '직무 면접'],
      ['2차', '기술 리더 면접'],
    ])

    // The new round starts empty: copy 1차's dictionary, then let AI add questions.
    await user.click(await screen.findByRole('button', { name: '1차 역량 복사' }))
    const editor = await screen.findByTestId('preset-editor', {}, { timeout: 5000 })
    await user.click(within(editor).getByRole('button', { name: 'AI 질문 초안' }))
    await waitFor(() => expect(within(editor).getAllByRole('listitem').length).toBeGreaterThan(0), { timeout: 5000 })
    const round2 = db.roundsOf(P2)[1]!
    const set = db.latestSet(round2.id)!
    const first = db.presetsOf(db.approvedSet(db.roundsOf(P2)[0]!.id)!.id).map((q) => q.question)
    const drafted = db.presetsOf(set.id).map((q) => q.question)
    expect(drafted.length).toBeGreaterThan(0)
    expect(drafted.filter((q) => first.includes(q))).toEqual([])
  })
})
