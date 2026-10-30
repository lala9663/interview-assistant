import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Screening } from '@/api/types'
import { getDb } from '@/mocks/db'
import { P1 } from '@/mocks/data/postings'
import { formatYears } from '@/lib/labels'
import { renderPlain, renderRoute } from '@/test/render'

import ApplicationSheet from './ApplicationSheet.vue'
import ScreeningPage from './ScreeningPage.vue'
import ScreeningRationale from './ScreeningRationale.vue'

const applicationOf = (n: number) => `d1e2f3a4-0000-4000-9000-${String(n).padStart(12, '0')}`

function screening(p: Partial<Screening>): Screening {
  return {
    id: 's1',
    application_id: 'a1',
    fit_score: 72,
    rationale: '',
    assessment: null,
    recommendation: null,
    status: 'hold',
    reject_reason: null,
    model: 'm',
    prompt_version: 'screening-v0.5',
    created_at: '2026-10-30T00:00:00Z',
    ...p,
  }
}

describe('선별 근거', () => {
  it('shows a requirement table (필수 first), the recommendation as a badge and points to check', () => {
    renderPlain(ScreeningRationale, {
      screening: screening({
        recommendation: 'hold',
        assessment: {
          summary: '요건 일부는 맞지만 확인이 필요합니다.',
          requirements: [
            { kind: 'preferred', requirement: 'GPU 추론 서버 운영', verdict: 'unclear', evidence: '서류에 관련 내용이 없습니다.', source: '' },
            { kind: 'required', requirement: '백엔드 개발 경력 4년 이상', verdict: 'met', evidence: '백엔드 개발 경력이 7년입니다.', source: '경력 · [회사-1]' },
            { kind: 'required', requirement: 'RDBMS 모델링', verdict: 'unmet', evidence: '근거가 없습니다.', source: '' },
          ],
          interview_checks: ['정산 시스템 DB를 직접 설계했는지'],
        },
      }),
    })
    expect(screen.getByTestId('ai-recommendation')).toHaveTextContent('AI 권고 · 보류')
    const rows = screen.getAllByTestId('requirement-row')
    expect(rows.map((r) => within(r).getAllByRole('cell')[0]!.textContent?.trim())).toEqual([
      '필수 백엔드 개발 경력 4년 이상',
      '필수 RDBMS 모델링',
      '우대 GPU 추론 서버 운영',
    ])
    expect(within(rows[0]!).getByText('충족')).toBeInTheDocument()
    expect(within(rows[0]!).getByText(/위치:/)).toHaveTextContent('경력 · [회사-1]')
    expect(within(rows[1]!).getByText('미충족')).toBeInTheDocument()
    expect(within(rows[2]!).getByText('확인 필요')).toBeInTheDocument()
    expect(screen.getByTestId('interview-checks')).toHaveTextContent('정산 시스템 DB를 직접 설계했는지')
    expect(screen.queryByTestId('legacy-rationale')).toBeNull()
  })

  it('still shows rows screened before screening-v0.5 (free text), without the old "(AI 권고: …)" suffix', () => {
    renderPlain(ScreeningRationale, {
      screening: screening({ recommendation: 'rejected', prompt_version: 'screening-v0.4', rationale: '경력이 요건에 못 미칩니다. (AI 권고: 탈락)\n+ 디스플레이 공정 2년\n- 반도체 공정 경력 없음' }),
    })
    const legacy = screen.getByTestId('legacy-rationale')
    expect(legacy).toHaveTextContent('경력이 요건에 못 미칩니다.')
    expect(legacy).not.toHaveTextContent('AI 권고')
    expect(within(legacy).getByText('디스플레이 공정 2년')).toBeInTheDocument()
    expect(within(legacy).getByText('반도체 공정 경력 없음')).toBeInTheDocument()
    expect(screen.getByTestId('ai-recommendation')).toHaveTextContent('AI 권고 · 탈락')
    expect(screen.queryByTestId('requirement-table')).toBeNull()
  })

  it('says experience in one format', () => {
    expect([7.2, 7, 0.5, 12.0, 3.95].map(formatYears)).toEqual(['7년 2개월', '7년', '6개월', '12년', '3년 11개월'])
  })
})

describe('탈락 사유 (mock API)', { timeout: 30_000 }, () => {
  async function openSheet(n: number) {
    const id = applicationOf(n)
    await renderRoute(ApplicationSheet, { path: '/', url: '/', props: { applicationId: id, postingId: getDb().application(id)!.posting_id } })
    await screen.findByRole('heading', { name: '면접' })
    return id
  }

  it('asks for a reason before 탈락, keeps it on the screening and in the audit log', async () => {
    const user = userEvent.setup()
    const id = await openSheet(6) // 서류 보류
    const db = getDb()

    await user.click(screen.getByRole('radio', { name: '탈락' }))
    const dialog = await screen.findByRole('dialog', { name: /CAND-0006 탈락 사유/ })
    expect(db.screeningOf(id)!.status).toBe('hold') // nothing changes until a reason is saved
    const save = within(dialog).getByRole('button', { name: '탈락 처리' })
    expect(save).toBeDisabled()
    await user.type(within(dialog).getByLabelText('사유'), '최근 경력이 장비 유지보수 중심이라 공정 개발 근거가 부족합니다.')
    await user.click(save)

    await waitFor(() => expect(db.screeningOf(id)!.status).toBe('rejected'))
    expect(db.screeningOf(id)!.reject_reason).toBe('최근 경력이 장비 유지보수 중심이라 공정 개발 근거가 부족합니다.')
    expect(await screen.findByTestId('reject-reason')).toHaveTextContent('최근 경력이 장비 유지보수 중심이라')
    const entry = db.audit.find((a) => a.action === 'screening.status_changed')!
    expect(entry.details).toMatchObject({ from: 'hold', to: 'rejected', reason: '최근 경력이 장비 유지보수 중심이라 공정 개발 근거가 부족합니다.' })
  })

  it('cancelling leaves the status as it was', async () => {
    const user = userEvent.setup()
    const id = await openSheet(6)
    await user.click(screen.getByRole('radio', { name: '탈락' }))
    const dialog = await screen.findByRole('dialog', { name: /탈락 사유/ })
    await user.click(within(dialog).getByRole('button', { name: '취소' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /탈락 사유/ })).toBeNull())
    expect(getDb().screeningOf(id)!.status).toBe('hold')
    expect(screen.getByRole('radio', { name: '보류' })).toBeChecked()
  })

  it('shows the reason of an application already rejected', async () => {
    await openSheet(4)
    expect(screen.getByTestId('reject-reason')).toHaveTextContent('필수 경력 요건에 못 미칩니다')
  })
})

describe('지원자 상세 이동', { timeout: 30_000 }, () => {
  it('moves to the previous/next applicant in the list order with buttons and ←/→, but not while typing', async () => {
    const user = userEvent.setup()
    const db = getDb()
    // 접수순, the list's default order
    const order = db.applications.filter((a) => a.posting_id === P1.id).sort((a, b) => a.created_at.localeCompare(b.created_at))
    const pseudonym = (i: number) => db.candidate(order[i]!.candidate_id)!.pseudonym
    await renderRoute(ScreeningPage, { path: '/screening/:postingId', url: `/screening/${P1.id}?app=${order[1]!.id}` })

    const nav = await screen.findByTestId('sheet-nav')
    expect(nav).toHaveTextContent(`2 / ${order.length}`)
    expect(await screen.findByRole('heading', { name: new RegExp(pseudonym(1)) })).toBeInTheDocument()

    await user.keyboard('{ArrowRight}')
    expect(await screen.findByRole('heading', { name: new RegExp(pseudonym(2)) })).toBeInTheDocument()
    expect(screen.getByTestId('sheet-nav')).toHaveTextContent(`3 / ${order.length}`)

    await user.click(within(screen.getByTestId('sheet-nav')).getByRole('button', { name: '이전 지원자' }))
    expect(await screen.findByRole('heading', { name: new RegExp(pseudonym(1)) })).toBeInTheDocument()
    await user.keyboard('{ArrowLeft}')
    expect(await screen.findByRole('heading', { name: new RegExp(pseudonym(0)) })).toBeInTheDocument()
    expect(within(screen.getByTestId('sheet-nav')).getByRole('button', { name: '이전 지원자' })).toBeDisabled()

    // Typing in the reason box keeps the arrows for the text.
    await user.click(screen.getByRole('radio', { name: '탈락' }))
    const box = await screen.findByLabelText('사유')
    await user.type(box, '사유{ArrowRight}{ArrowRight}')
    expect(screen.getByTestId('sheet-nav')).toHaveTextContent(`1 / ${order.length}`)
  })
})
