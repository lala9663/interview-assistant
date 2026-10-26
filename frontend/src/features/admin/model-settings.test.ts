import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import CommandPalette from '@/components/layout/CommandPalette.vue'
import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import ModelSettingsPage from './ModelSettingsPage.vue'

const renderPage = () => renderRoute(ModelSettingsPage, { path: '/admin/models', url: '/admin/models' })

const card = async (role: string) => {
  const cards = await screen.findAllByTestId('role-card')
  return cards.find((c) => c.dataset.role === role)!
}

const next = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: /다음/ }))

describe('관리자 > 모델 설정', () => {
  it('shows the six roles with provider, model, status and where their data goes', async () => {
    await renderPage()
    const cards = await screen.findAllByTestId('role-card')
    expect(cards.map((c) => c.dataset.role)).toEqual(['llm.primary', 'llm.screening', 'stt.streaming', 'stt.batch', 'embedding', 'diarization'])
    const primary = await card('llm.primary')
    expect(within(primary).getByText('Claude (Vertex AI)')).toBeInTheDocument()
    expect(within(primary).getByTestId('role-model')).toHaveTextContent('claude-opus-5-5')
    expect(within(primary).getByTestId('data-location')).toHaveTextContent('사내 GCP')
    expect(within(primary).getByText('사용 가능')).toBeInTheDocument()
    expect(await screen.findAllByTestId('history-row')).toHaveLength(6)
  })

  it('switches the batch STT to local Whisper: download, check, test, reason, apply, history, rollback', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('stt.batch')).getByRole('button', { name: 'STT 사후 변경' }))

    // 1. provider
    await user.click(await screen.findByTestId('impl-faster_whisper'))
    await next(user)
    // 2. model: large-v3 is the batch recommendation; take small, which needs a download first
    expect(screen.getByTestId('model-choice-large-v3')).toHaveAttribute('aria-checked', 'true')
    expect(within(screen.getByTestId('model-choice-large-v3')).getByText('사후 권장')).toBeInTheDocument()
    await user.click(screen.getByTestId('model-choice-small'))
    await user.type(screen.getByLabelText('기술 용어 힌트'), 'CMP, 식각, 수율')
    await next(user)
    // 3. requirements: weights missing
    expect(await screen.findByText(/아직 내려받지 않았습니다/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /다음/ })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /이전/ }))
    await user.click(within(screen.getByTestId('model-choice-small')).getByRole('button', { name: /다운로드 486MB/ }))
    await waitFor(() => expect(within(screen.getByTestId('model-choice-small')).getByText('내려받음')).toBeInTheDocument(), { timeout: 4000 })
    await next(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    // 4. test on the built-in Korean sample (microphone needs a browser with MediaRecorder)
    await next(user)
    await user.click(screen.getByRole('radio', { name: '마이크로 테스트' }))
    await user.click(screen.getByRole('button', { name: /녹음 시작/ }))
    expect(await screen.findByText(/녹음을 지원하지 않습니다/)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: '내장 샘플' }))
    await user.click(screen.getByTestId('run-test'))
    const result = await screen.findByTestId('test-result')
    expect(result).toHaveAttribute('data-ok', 'true')
    expect(within(result).getByTestId('transcript')).toHaveTextContent('커리는 약용 식물과 향신료를')
    expect(within(result).getByText('CER 0.0%')).toBeInTheDocument()
    // 5. reason and apply
    await next(user)
    expect(screen.getByTestId('apply')).toBeDisabled()
    await user.type(screen.getByLabelText('변경 사유'), '사후 전사를 로컬 Whisper로')
    await user.click(screen.getByTestId('apply'))

    await waitFor(async () => expect(within(await card('stt.batch')).getByTestId('role-model')).toHaveTextContent('faster-whisper-small'))
    expect(within(await card('stt.batch')).getByTestId('data-location')).toHaveTextContent('이 PC')
    const rows = await screen.findAllByTestId('history-row')
    await waitFor(() => expect(screen.getAllByTestId('history-row')).toHaveLength(7))
    const latest = screen.getAllByTestId('history-row')[0]!
    expect(latest).toHaveTextContent('김서연')
    expect(latest).toHaveTextContent('사후 전사를 로컬 Whisper로')
    expect(latest).toHaveTextContent('Whisper (로컬, faster-whisper) · small')
    expect(rows.length).toBeGreaterThan(0)
    expect(getDb().models.active['stt.batch'].options.initial_prompt).toBe('CMP, 식각, 수율')

    // rollback
    await user.click(within(latest).getByRole('button', { name: /되돌리기/ }))
    await user.type(screen.getByLabelText('사유'), '원래대로')
    await user.click(screen.getByTestId('confirm-revert'))
    await waitFor(async () => expect(within(await card('stt.batch')).getByTestId('role-model')).toHaveTextContent('chirp_3'))
    await waitFor(() => expect(screen.getAllByTestId('history-row')[0]).toHaveTextContent('되돌림'))
  })

  it('a provider that sends data outside the company needs the warning step', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('llm.primary')).getByRole('button', { name: 'LLM 주 모델 변경' }))
    await user.click(await screen.findByTestId('impl-anthropic_api'))
    expect(screen.getByRole('list', { name: '단계' })).toHaveTextContent('외부 전송')
    await next(user)
    await next(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    await next(user)
    expect(screen.getByTestId('external-warning')).toHaveTextContent('회사 밖 API로 데이터를 보내는 provider입니다.')
    expect(screen.getByRole('button', { name: /다음/ })).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    await next(user)
    await user.click(screen.getByTestId('run-test'))
    expect(await screen.findByTestId('test-result')).toHaveAttribute('data-ok', 'true')
    await next(user)
    await user.type(screen.getByLabelText('변경 사유'), '외부 API 비교')
    await user.click(screen.getByTestId('apply'))
    await waitFor(async () => expect(within(await card('llm.primary')).getByTestId('data-location')).toHaveTextContent('외부'))
    expect(getDb().models.history[0]!.details).toMatchObject({ confirmed_external: true })
  })

  it('is for admins only: no menu item, no page', async () => {
    getDb().me.is_admin = false
    await renderPage()
    expect(await screen.findByText('관리자만 볼 수 있습니다')).toBeInTheDocument()
    expect(screen.queryAllByTestId('role-card')).toHaveLength(0)
  })

  it('the command palette offers 모델 설정 to admins only', async () => {
    const user = userEvent.setup()
    const { unmount } = await renderRoute(CommandPalette, { path: '/', url: '/', props: { open: true } })
    const input = await screen.findByPlaceholderText(/화면, 지원자/)
    await user.type(input, '모델')
    expect(await screen.findByRole('option', { name: /모델 설정/ })).toBeInTheDocument()
    unmount()

    getDb().me.is_admin = false
    await renderRoute(CommandPalette, { path: '/', url: '/', props: { open: true } })
    await user.type(await screen.findByPlaceholderText(/화면, 지원자/), '모델')
    await screen.findByText('결과가 없습니다.')
    expect(screen.queryByRole('option', { name: /모델 설정/ })).toBeNull()
  })
})
