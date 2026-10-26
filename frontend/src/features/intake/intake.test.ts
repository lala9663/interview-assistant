import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import CommandPalette from '@/components/layout/CommandPalette.vue'
import PostingDetailPage from '@/features/postings/PostingDetailPage.vue'
import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import IntakePage from './IntakePage.vue'

const P1 = 'b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0001'
const P3 = 'b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0003'
const renderPage = () => renderRoute(IntakePage, { path: '/admin/intake', url: '/admin/intake' })

describe('관리자 > 연동 현황', () => {
  it('lists what the site sent with status, reason and pseudonym only, and counts per posting', async () => {
    await renderPage()
    const rows = await screen.findAllByTestId('intake-event-row')
    expect(rows).toHaveLength(getDb().intake.events.length)
    const failed = rows.filter((r) => r.dataset.status === 'failed')
    expect(failed.map((r) => within(r).getByTestId('intake-reason').textContent)).toEqual([
      '스캔본 (OCR 필요)',
      '지원하지 않는 첨부 형식',
      '모르는 공고 번호',
      '모르는 공고 번호',
      '모르는 공고 번호',
    ])
    for (const r of failed) expect(within(r).getByRole('button', { name: /다시 처리/ })).toBeInTheDocument()
    const rejected = rows.filter((r) => r.dataset.status === 'rejected')
    expect(rejected).toHaveLength(2)
    for (const r of rejected) expect(within(r).queryByRole('button', { name: /다시 처리/ })).toBeNull()
    expect(rejected.map((r) => within(r).getByTestId('intake-reason').textContent)).toEqual(['필수 칸 누락', '받지 않는 항목'])

    const site = getDb().applications.filter((a) => a.channel === 'site')
    const pseudonyms = site.map((a) => getDb().candidate(a.candidate_id)!.pseudonym)
    for (const p of pseudonyms) expect(screen.getAllByText(p).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toMatch(/U\d{6}/) // applicant numbers are never stored or shown

    const postings = screen.getAllByTestId('intake-posting-row')
    const unlinked = postings.find((r) => r.textContent?.includes('DS-2026-0103'))!
    expect(within(unlinked).getByText('연결된 공고 없음')).toBeInTheDocument()
    expect(postings.find((r) => r.textContent?.includes('메모리 공정개발 엔지니어'))!).toHaveTextContent('DS-2026-0101')
    expect(screen.getAllByTestId('intake-failure').map((f) => f.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('모르는 공고 번호')]),
    )
  })

  it('after the posting number is linked, 다시 처리 turns the waiting applications into screened ones', async () => {
    const user = userEvent.setup()
    getDb().posting(P3)!.site_posting_no = 'DS-2026-0103'
    const before = getDb().applications.length
    await renderPage()
    const failure = (await screen.findAllByTestId('intake-failure')).find((f) => f.textContent?.includes('모르는 공고 번호'))!
    await user.click(within(failure).getByRole('button', { name: '모르는 공고 번호 모두 다시 처리' }))
    await waitFor(() => expect(getDb().applications.length).toBe(before + 3), { timeout: 4000 })
    const created = getDb().applications.slice(before)
    expect(created.every((a) => a.posting_id === P3 && a.channel === 'site')).toBe(true)
    await waitFor(() => expect(screen.queryByText('모르는 공고 번호')).toBeNull(), { timeout: 4000 })
    const done = screen.getAllByTestId('intake-event-row').filter((r) => r.dataset.status === 'done' && r.textContent?.includes('DS-2026-0103'))
    expect(done).toHaveLength(3)
    expect(done.map((r) => within(r).getByText(/CAND-/).textContent).sort()).toEqual(['CAND-0021', 'CAND-0022', 'CAND-0023'])
  })

  it('a failure that cannot pass yet fails again; a refused event cannot be retried', async () => {
    const user = userEvent.setup()
    await renderPage()
    const hwp = (await screen.findAllByTestId('intake-event-row')).find((r) => r.textContent?.includes('지원하지 않는 첨부 형식'))!
    await user.click(within(hwp).getByRole('button', { name: /다시 처리/ }))
    await waitFor(
      () => {
        const again = getDb().intake.events.find((e) => e.application_no === 'A100211')!
        expect(again.status).toBe('failed')
        expect(again.attempts).toBe(2)
      },
      { timeout: 4000 },
    )
    expect(getDb().audit.some((a) => a.action === 'intake.retried')).toBe(true)
  })

  it('is for admins only, in the menu and on the page', async () => {
    const me = getDb().me
    await renderRoute(CommandPalette, { path: '/', url: '/', props: { open: true } })
    expect(await screen.findByRole('option', { name: /연동 현황/ })).toBeInTheDocument()
    me.is_admin = false
    await renderPage()
    expect(await screen.findByText('관리자만 볼 수 있습니다')).toBeInTheDocument()
  })
})

describe('공고 상세 > 채용 사이트 공고 번호', () => {
  it('links, refuses a number another posting uses, and unlinks', async () => {
    const user = userEvent.setup()
    await renderRoute(PostingDetailPage, { path: '/postings/:postingId', url: `/postings/${P3}` })
    const card = await screen.findByTestId('site-link-card')
    const input = within(card).getByLabelText('채용 사이트 공고 번호')
    expect(input).toHaveValue('')

    await user.type(input, 'DS-2026-0101')
    await user.click(within(card).getByRole('button', { name: '저장' }))
    await waitFor(() => expect(getDb().posting(P3)!.site_posting_no).toBeNull())
    expect(getDb().posting(P1)!.site_posting_no).toBe('DS-2026-0101') // taken: 409, nothing changed

    await user.clear(input)
    await user.type(input, '공고 1')
    expect(within(card).getByText(/영문·숫자와/)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: '저장' })).toBeDisabled()

    await user.clear(input)
    await user.type(input, 'DS-2026-0103')
    await user.click(within(card).getByRole('button', { name: '저장' }))
    await waitFor(() => expect(getDb().posting(P3)!.site_posting_no).toBe('DS-2026-0103'))
    expect(await screen.findByText('사이트 DS-2026-0103')).toBeInTheDocument()
    expect(getDb().audit[0]).toMatchObject({ action: 'posting.site_linked', details: { from: null, to: 'DS-2026-0103' } })

    await user.clear(input)
    await user.click(within(card).getByRole('button', { name: /연결 해제/ }))
    await waitFor(() => expect(getDb().posting(P3)!.site_posting_no).toBeNull())
  })
})
