import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { endpoints } from '@/api/endpoints'
import type { ImportResult } from '@/api/types'
import FollowUpMetricsPage from '@/features/admin/FollowUpMetricsPage.vue'
import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import QuestionBankPage from './QuestionBankPage.vue'

const renderBank = (url = '/question-bank') => renderRoute(QuestionBankPage, { path: '/question-bank', url })
const WAIT = { timeout: 4000 }

describe('질문 은행', { timeout: 30_000 }, () => {
  it('lists approved, draft and retired questions with the prohibited-question warning on the flagged draft', async () => {
    await renderBank()
    const items = await screen.findAllByTestId('bank-item')
    expect(items).toHaveLength(getDb().bank.questions.length)
    const flagged = items.filter((i) => within(i).queryByTestId('bank-flags'))
    expect(flagged).toHaveLength(1)
    expect(flagged[0]!.dataset.status).toBe('draft')
    expect(within(flagged[0]!).getByText('혼인·연애')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /승인/ })).toHaveTextContent(String(getDb().bank.questions.filter((q) => q.status === 'approved').length))

    const user = userEvent.setup()
    await user.click(screen.getByRole('radio', { name: /폐기/ }))
    await waitFor(() => expect(screen.getAllByTestId('bank-item')).toHaveLength(1), WAIT)
    expect(screen.getByTestId('bank-item').dataset.status).toBe('retired')
  })

  it('approving a flagged question asks for confirmation and records it approved', async () => {
    const user = userEvent.setup()
    await renderBank()
    const flagged = (await screen.findAllByTestId('bank-item')).find((i) => within(i).queryByTestId('bank-flags'))!
    await user.click(within(flagged).getByRole('button', { name: '승인' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/금지 질문 경고가 있는 질문입니다/)).toBeInTheDocument()
    expect(within(dialog).getByText('혼인·연애')).toBeInTheDocument()
    await user.click(within(dialog).getByTestId('confirm-approve'))
    await waitFor(() => expect(getDb().bank.questions.find((q) => q.question.startsWith('결혼 계획'))!.status).toBe('approved'), WAIT)
  })

  it('warns while typing a prohibited question and saves it as a draft', async () => {
    const user = userEvent.setup()
    await renderBank()
    await screen.findAllByTestId('bank-item')
    await user.click(screen.getByRole('button', { name: '질문 추가' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('combobox', { name: '역량' }))
    await user.click(await screen.findByRole('option', { name: '공정 문제 해결' }))
    await user.type(within(dialog).getByLabelText('질문'), '부모님은 어떤 일을 하시나요?')
    expect(await within(dialog).findByText('가족 사항', {}, WAIT)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/좋은 꼬리질문 예시/), '그 일에서 배운 점은?')
    await user.click(within(dialog).getByRole('button', { name: '초안으로 저장' }))
    await waitFor(() => expect(getDb().bank.questions.at(-1)!.question).toBe('부모님은 어떤 일을 하시나요?'), WAIT)
    const saved = getDb().bank.questions.at(-1)!
    expect(saved).toMatchObject({ status: 'draft', job_family: '공정개발', follow_ups: ['그 일에서 배운 점은?'] })
    expect(saved.flags.map((f) => f.category)).toEqual(['family'])
  })

  it('imports a CSV after a dry run, as drafts', async () => {
    // jsdom's FormData cannot go through Node's fetch (see the upload test): the endpoint is stubbed with the
    // mock API's own rules, and the request it would send is checked instead.
    const calls: boolean[] = []
    vi.spyOn(endpoints, 'importQuestions').mockImplementation(async (_file, dryRun) => {
      calls.push(dryRun)
      const result: ImportResult = {
        dry_run: dryRun,
        rows: 3,
        created: 2,
        skipped: 1,
        errors: [],
        warnings: [{ row: 3, message: '금지 질문 경고: 임신·출산·육아 계획' }],
      }
      if (!dryRun) {
        for (const q of ['FDC 알람이 잦을 때 실제 이상과 오탐을 어떻게 가렸나요?', '자녀 계획이 있으신가요?']) {
          getDb().bank.questions.push({ ...getDb().bank.questions[0]!, id: q, question: q, status: 'draft', source: 'csv' })
        }
      }
      return result
    })
    const user = userEvent.setup()
    await renderBank()
    await screen.findAllByTestId('bank-item')
    await user.click(await screen.findByRole('button', { name: 'CSV 가져오기' }))
    const dialog = await screen.findByRole('dialog')
    const csv = [
      '직군,역량,차수,질문,의도,꼬리질문 예시',
      '공정개발,데이터 기반 분석,1차,FDC 알람이 잦을 때 실제 이상과 오탐을 어떻게 가렸나요?,알람 품질,알람 기준은? | 오탐을 줄인 결과는?',
      '공정개발,데이터 기반 분석,,FDC 데이터에서 이상 징후를 찾을 때 어떤 변수부터 보나요?,,',
      '공정개발,조직 적합과 성장 의지,2,자녀 계획이 있으신가요?,,',
    ].join('\n')
    await user.upload(within(dialog).getByLabelText(/CSV 파일/), new File([csv], 'bank.csv', { type: 'text/csv' }))
    const before = getDb().bank.questions.length
    await user.click(within(dialog).getByRole('button', { name: '미리 보기' }))
    const preview = await within(dialog).findByTestId('import-preview', {}, WAIT)
    expect(preview).toHaveTextContent('3행 중 2개를 초안으로 추가합니다.')
    expect(preview).toHaveTextContent('이미 있는 질문 1개는 건너뜁니다.')
    expect(preview).toHaveTextContent('3행: 금지 질문 경고: 임신·출산·육아 계획')
    expect(getDb().bank.questions).toHaveLength(before)
    await user.click(within(dialog).getByRole('button', { name: '초안 2개 가져오기' }))
    await waitFor(() => expect(getDb().bank.questions).toHaveLength(before + 2), WAIT)
    expect(getDb().bank.questions.slice(-2).every((q) => q.status === 'draft' && q.source === 'csv')).toBe(true)
    expect(calls).toEqual([true, false])
  })

  it('interviewers who are not admins write drafts but do not approve', async () => {
    getDb().me.is_admin = false
    await renderBank()
    const items = await screen.findAllByTestId('bank-item')
    expect(screen.getByRole('button', { name: '질문 추가' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'CSV 가져오기' })).toBeNull()
    for (const i of items) expect(within(i).queryByRole('button', { name: '승인' })).toBeNull()
  })
})

describe('평점 기준 예시', { timeout: 30_000 }, () => {
  it('groups anchors by competency and flags an anchor that reads like another score', async () => {
    const user = userEvent.setup()
    const three = getDb().bank.rubric.find((r) => r.competency === '공정 문제 해결' && r.score === 3)!
    await renderBank('/question-bank?tab=rubric')
    const groups = await screen.findAllByTestId('rubric-group')
    expect(groups.map((g) => g.querySelector('h3')!.textContent)).toEqual(
      expect.arrayContaining(['공정개발 · 공정 문제 해결', '공정개발 · 데이터 기반 분석', 'SW개발 · 시스템 설계']),
    )
    expect(screen.getByText(/채점은 이 예시와의 유사도로 하지 않습니다/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '예시 추가' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('combobox', { name: '역량' }))
    await user.click(await screen.findByRole('option', { name: '공정 문제 해결' }))
    await user.click(within(dialog).getByRole('radio', { name: '4점' }))
    await user.type(within(dialog).getByLabelText('예시 답변'), three.answer)
    await user.click(within(dialog).getByRole('button', { name: '초안으로 저장' }))
    await waitFor(() => expect(getDb().bank.rubric.at(-1)!.score).toBe(4), WAIT)
    expect(await screen.findByTestId('rubric-overlap', {}, WAIT)).toHaveTextContent('3점 예시와 거의 같습니다')
  })
})

describe('관리자 > 꼬리질문 지표', { timeout: 30_000 }, () => {
  it('shows adoption and timing by source, duplicates and the embedding index', async () => {
    const db = getDb()
    const at = Date.now()
    db.bank.shown.push(
      { batch_id: 'b1', suggestion_id: 's1', source: 'bank', latency_ms: 420, discarded: false, used: true, edited: false, at },
      { batch_id: 'b1', suggestion_id: 's2', source: 'ai', latency_ms: 1600, discarded: false, used: false, edited: false, at },
      { batch_id: 'b1', suggestion_id: 's3', source: 'ai', latency_ms: 1900, discarded: true, used: false, edited: false, at },
    )
    const user = userEvent.setup()
    await renderRoute(FollowUpMetricsPage, { path: '/admin/follow-up-metrics', url: '/admin/follow-up-metrics' })
    const table = await screen.findByTestId('metrics-table')
    const bank = within(table).getAllByRole('row').find((r) => r.dataset.source === 'bank')!
    expect(bank).toHaveTextContent('100%')
    expect(bank).toHaveTextContent('420ms')
    expect(screen.getByTestId('metrics-tiles')).toHaveTextContent('질문 은행 0')
    expect(screen.getByTestId('metrics-tiles')).toHaveTextContent('AI 1')

    const index = screen.getByTestId('embedding-index')
    expect(await within(index).findByText('BAAI/bge-m3')).toBeInTheDocument()
    await user.click(within(index).getByRole('button', { name: '다시 만들기' }))
    expect(await within(index).findByTestId('index-building', {}, WAIT)).toHaveTextContent('새 색인 만드는 중')
  })

  it('is for admins only', async () => {
    getDb().me.is_admin = false
    await renderRoute(FollowUpMetricsPage, { path: '/admin/follow-up-metrics', url: '/admin/follow-up-metrics' })
    expect(await screen.findByText('관리자만 볼 수 있습니다')).toBeInTheDocument()
  })
})
