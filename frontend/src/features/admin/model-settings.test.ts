import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import CommandPalette from '@/components/layout/CommandPalette.vue'
import { getDb } from '@/mocks/db'
import { SERVER_MODEL } from '@/mocks/models'
import { renderRoute } from '@/test/render'

import ModelSettingsPage from './ModelSettingsPage.vue'

const renderPage = () => renderRoute(ModelSettingsPage, { path: '/admin/models', url: '/admin/models' })

const card = async (role: string) => {
  const cards = await screen.findAllByTestId('role-card')
  return cards.find((c) => c.dataset.role === role)!
}

const next = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: /다음/ }))

describe('관리자 > 모델 설정', { timeout: 20_000 }, () => {
  it('shows the AI roles, the 서류 읽기 roles and the 음성 입력 roles with provider, model, status and where their data goes', async () => {
    await renderPage()
    await screen.findAllByTestId('role-card')
    const ai = within(screen.getByTestId('group-ai')).getAllByTestId('role-card')
    expect(ai.map((c) => c.dataset.role)).toEqual(['llm.primary', 'llm.screening', 'stt.streaming', 'stt.batch', 'embedding', 'diarization'])
    const docs = within(screen.getByTestId('group-documents')).getAllByTestId('role-card')
    expect(docs.map((c) => c.dataset.role)).toEqual(['document.reading', 'document.ocr', 'document.pdf', 'document.hwp', 'document.legacy'])
    expect(screen.getByRole('heading', { name: '서류 읽기' })).toBeInTheDocument()
    const audio = within(screen.getByTestId('group-audio')).getAllByTestId('role-card')
    expect(audio.map((c) => c.dataset.role)).toEqual(['audio.vad', 'audio.turn', 'audio.denoise'])
    expect(within(await card('audio.turn')).getByText('Smart Turn v3 (로컬)')).toBeInTheDocument()
    const ocr = await card('document.ocr')
    expect(within(ocr).getByText('PaddleOCR (로컬, PP-OCRv5 한국어)')).toBeInTheDocument()
    expect(within(ocr).getByTestId('data-location')).toHaveTextContent('이 PC')
    const primary = await card('llm.primary')
    expect(within(primary).getByText('오픈소스 모델 서버 (vLLM·Ollama 등)')).toBeInTheDocument()
    expect(within(primary).getByTestId('role-model')).toHaveTextContent(SERVER_MODEL)
    expect(within(primary).getByTestId('data-location')).toHaveTextContent('설정한 사내 서버')
    expect(within(primary).getByText('사용 가능')).toBeInTheDocument()
    expect(within(await card('stt.batch')).getByTestId('data-location')).toHaveTextContent('외부 클라우드 (Google)')
    expect(await screen.findAllByTestId('history-row')).toHaveLength(14) // one initial row per role
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
    await waitFor(() => expect(screen.getAllByTestId('history-row')).toHaveLength(15))
    const latest = screen.getAllByTestId('history-row')[0]!
    expect(latest).toHaveTextContent('김서연')
    expect(latest).toHaveTextContent('사후 전사를 로컬 Whisper로')
    expect(latest).toHaveTextContent('Whisper (로컬, faster-whisper) · small')
    expect(rows.length).toBeGreaterThan(0)
    expect(getDb().models.active['stt.batch'].options.initial_prompt).toBe('CMP, 식각, 수율')

    // rollback: back to Google Cloud, outside the company, so the transfer is confirmed first
    await user.click(within(latest).getByRole('button', { name: /되돌리기/ }))
    await user.type(screen.getByLabelText('사유'), '원래대로')
    expect(screen.getByText('회사 밖 API로 데이터를 보내는 설정으로 돌아갑니다.')).toBeInTheDocument()
    expect(screen.getByTestId('confirm-revert')).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByTestId('confirm-revert'))
    await waitFor(async () => expect(within(await card('stt.batch')).getByTestId('role-model')).toHaveTextContent('chirp_3'))
    await waitFor(() => expect(screen.getAllByTestId('history-row')[0]).toHaveTextContent('되돌림'))
  })

  it('points the main LLM at another in-house model server: OpenAI addresses refused, timings and the served models shown', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('llm.primary')).getByRole('button', { name: 'LLM 주 모델 변경' }))
    expect(within(await screen.findByTestId('impl-open_model_server')).getByTestId('data-location')).toHaveTextContent('설정한 사내 서버')
    expect(screen.getByRole('list', { name: '단계' })).not.toHaveTextContent('외부 전송')
    await next(user)
    // 2. options: the current server is filled in; an OpenAI address is refused on the check
    const url = screen.getByLabelText('서버 주소')
    expect(url).toHaveValue('http://vllm.internal:8000/v1')
    await user.clear(url)
    await user.type(url, 'https://api.openai.com/v1')
    await next(user)
    expect(await screen.findByText(/OpenAI 서비스 주소는 쓸 수 없습니다/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /이전/ }))
    await user.clear(screen.getByLabelText('서버 주소'))
    await user.type(screen.getByLabelText('서버 주소'), 'http://ollama.internal:11434/v1/')
    await user.clear(screen.getByLabelText('모델 이름'))
    await user.type(screen.getByLabelText('모델 이름'), 'gemma4:12b')
    await user.type(screen.getByLabelText('API 키 환경변수 이름'), 'IA_LLM_API_KEY')
    await next(user)
    expect(await screen.findByText('환경변수 IA_LLM_API_KEY')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    // 3. test: response time, first token, the server's models
    await next(user)
    await user.click(screen.getByTestId('run-test'))
    const result = await screen.findByTestId('test-result')
    expect(result).toHaveAttribute('data-ok', 'true')
    expect(within(result).getByTestId('first-token')).toHaveTextContent('첫 토큰 0.3초')
    expect(within(result).getByText('응답 0.8초')).toBeInTheDocument()
    expect(within(result).getByTestId('server-models')).toHaveTextContent('gemma4:12b')
    await next(user)
    await user.type(screen.getByLabelText('변경 사유'), '사내 Ollama 서버로 비교')
    await user.click(screen.getByTestId('apply'))
    await waitFor(async () => expect(within(await card('llm.primary')).getByTestId('role-model')).toHaveTextContent('gemma4:12b'))
    expect(getDb().models.active['llm.primary'].options).toMatchObject({ base_url: 'http://ollama.internal:11434/v1', api_key_env: 'IA_LLM_API_KEY' })
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

  it('switches the OCR engine to Tesseract: download its language data, read the sample, apply, roll back', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('document.ocr')).getByRole('button', { name: 'OCR 엔진 변경' }))
    await user.click(await screen.findByTestId('impl-tesseract'))
    await next(user)
    await user.click(within(screen.getByTestId('model-choice-fast')).getByRole('button', { name: /다운로드 6MB/ }))
    await user.click(screen.getByTestId('model-choice-fast'))
    await waitFor(() => expect(within(screen.getByTestId('model-choice-fast')).getByText('내려받음')).toBeInTheDocument(), { timeout: 4000 })
    await next(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    expect(screen.getByText('프로그램 Tesseract')).toBeInTheDocument()
    await next(user)
    expect(screen.getByText(/가상 이력서 PNG/)).toBeInTheDocument()
    await user.click(screen.getByTestId('run-test'))
    const result = await screen.findByTestId('test-result')
    expect(result).toHaveAttribute('data-ok', 'true')
    const pages = within(result).getByTestId('reading-pages')
    expect(within(pages).getAllByRole('row')).toHaveLength(3)
    expect(pages.querySelector('[data-method="ocr"]')).toHaveTextContent('Tesseract')
    expect(within(result).getByTestId('reading-images')).toHaveTextContent('증명사진: 읽지 않고 버림')
    expect(within(result).getByTestId('reading-preview')).toHaveTextContent('[지원자]')
    await next(user)
    await user.type(screen.getByLabelText('변경 사유'), 'Tesseract와 비교')
    await user.click(screen.getByTestId('apply'))
    await waitFor(async () => expect(within(await card('document.ocr')).getByTestId('role-model')).toHaveTextContent('Tesseract kor+eng (fast)'))

    await waitFor(() => expect(screen.getAllByTestId('history-row')[0]).toHaveTextContent('Tesseract (로컬, 비교용) · fast'))
    const latest = screen.getAllByTestId('history-row')[0]!
    await user.click(within(latest).getByRole('button', { name: /되돌리기/ }))
    await user.type(screen.getByLabelText('사유'), 'PaddleOCR로 복귀')
    await user.click(screen.getByTestId('confirm-revert'))
    await waitFor(async () => expect(within(await card('document.ocr')).getByTestId('role-model')).toHaveTextContent('PP-OCRv5 mobile 한국어'))
  })

  it('server noise suppression: DeepFilterNet3 needs its file, then the test shows the delay and how much quieter the rest got', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('audio.denoise')).getByRole('button', { name: '서버 잡음 억제 변경' }))
    expect(within(await screen.findByTestId('impl-rnnoise')).getByText(/지연 약 35ms/)).toBeInTheDocument()
    await user.click(screen.getByTestId('impl-deepfilternet'))
    await next(user)
    expect(screen.getByLabelText('앞 문맥 (ms)')).toHaveValue(300)
    await user.click(within(screen.getByTestId('model-choice-deepfilternet3')).getByRole('button', { name: /다운로드 9MB/ }))
    await waitFor(() => expect(within(screen.getByTestId('model-choice-deepfilternet3')).getByText('내려받음')).toBeInTheDocument(), { timeout: 4000 })
    await next(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    await next(user)
    expect(screen.getByRole('radiogroup', { name: '테스트 음성' })).toBeInTheDocument() // sample, microphone or a file
    await user.click(screen.getByTestId('run-test'))
    const result = await screen.findByTestId('test-result')
    expect(result).toHaveAttribute('data-ok', 'true')
    expect(within(result).getByTestId('denoise-delay')).toHaveTextContent('지연 45ms')
    expect(within(result).getByTestId('denoise-levels')).toHaveTextContent('말소리 -0.6dB · 그 밖 -14.2dB')
  })

  it('the text-only reading mode holds pages that need OCR in the test, as intended', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('document.reading')).getByRole('button', { name: '읽기 방식 변경' }))
    await next(user)
    await user.click(screen.getByRole('combobox', { name: '읽기 방식' }))
    await user.click(await screen.findByRole('option', { name: '텍스트만 (OCR 안 함)' }))
    await next(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled())
    await next(user)
    await user.click(screen.getByTestId('run-test'))
    const result = await screen.findByTestId('test-result')
    expect(result).toHaveAttribute('data-ok', 'true') // holding is what the setting is for: it can be applied
    expect(result).toHaveTextContent('보류합니다')
    expect(within(result).getByTestId('reading-pages').querySelector('[data-method="held"]')).not.toBeNull()
    expect(screen.getByRole('button', { name: /다음/ })).toBeEnabled()
  })

  it('an external OCR service warns that original page images leave the company', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(within(await card('document.ocr')).getByRole('button', { name: 'OCR 엔진 변경' }))
    const clova = await screen.findByTestId('impl-clova_ocr')
    expect(clova).toHaveTextContent('외부')
    expect(clova).toHaveTextContent('구현: 아직 구현되지 않았습니다.')
    await user.click(clova)
    expect(screen.getByRole('list', { name: '단계' })).toHaveTextContent('외부 전송')
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
