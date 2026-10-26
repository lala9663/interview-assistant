/**
 * Mock 관리자 > 모델 설정: the catalog (mirrors `providers/catalog.py`), the active spec per role, the change
 * history, simulated weight downloads and connection tests. The mock world runs the PoC config
 * (`config/providers.yaml`: Claude on Vertex AI, Chirp) as if GCP were set up, so the screen shows
 * every data location; `anthropic_api` exists only here, to show the external-transfer warning.
 */
import type {
  DataLocation,
  ModelChange,
  ModelImpl,
  ModelOptionField,
  ModelOptionValue,
  ModelRequirement,
  ModelRole,
  ModelRoleState,
  ModelSpec,
  ModelTestResult,
} from '@/api/types'
import { MODEL_ROLES } from '@/api/types'

export const ROLE_INFO: Record<ModelRole, { label: string; description: string }> = {
  'llm.primary': { label: 'LLM 주 모델', description: '역량 사전 초안, 꼬리질문, AI 채점' },
  'llm.screening': { label: 'LLM 선별용', description: '서류 구조화와 선별' },
  'stt.streaming': { label: 'STT 실시간', description: '면접 중 지원자 답변 전사' },
  'stt.batch': { label: 'STT 사후', description: '녹음 파일 전사 (10단계)' },
  embedding: { label: '임베딩', description: '검색·유사도 (후순위)' },
  diarization: { label: '화자분리', description: '대면 면접 화자 구분 (10단계)' },
}

export const SAMPLE_TEXT = '커리는 약용 식물과 향신료를 기본으로 하여 고기나 채소를 곁들이는 요리입니다.'

const field = (key: string, label: string, type: ModelOptionField['type'], def: ModelOptionValue | null, extra: Partial<ModelOptionField> = {}): ModelOptionField => ({
  key,
  label,
  type,
  default: def,
  help: '',
  minimum: null,
  maximum: null,
  max_length: 100,
  choices: [],
  roles: [],
  fixed: false,
  ...extra,
})
const choice = (value: string, label: string, note = '', extra: Partial<ModelOptionField['choices'][number]> = {}) => ({
  value,
  label,
  note,
  size_bytes: null,
  recommended_for: [],
  downloaded: null,
  ...extra,
})
const ko = field('language', '언어', 'string', 'ko-KR', { help: '한국어로 고정합니다.', fixed: true })
const speed = field('speed', '지연 흉내 속도', 'number', 1, { help: '1이면 데모 속도, 0이면 지연 없이 바로 답합니다.', minimum: 0, maximum: 5 })
const batchDiarization = field('diarization', '화자 구분', 'boolean', false, { help: '사후 전사에서 화자 라벨을 붙입니다.', roles: ['stt.batch'] })
const GCP_NOTE = '사내 GCP 프로젝트 안에서 처리합니다. 회사 밖 API로는 보내지 않습니다.'
const LIVE_NOTE =
  '실시간 면접의 음성 입력(마이크·WebRTC)은 다음 단계에서 붙습니다. 그 전까지 진행 중 면접 화면은 가상 지원자 대본(텍스트)을 보내므로, fake가 아닌 STT로 바꾸면 새로 시작하는 면접의 전사가 꺼지고 수기 답변 입력으로 바뀝니다. 지금 진행 중인 면접은 시작할 때의 STT를 계속 씁니다.'

export const WHISPER_SIZES: Record<string, number> = {
  small: 486_212_372,
  medium: 1_530_571_735,
  'large-v3': 3_090_835_702,
  'large-v3-turbo': 1_621_665_983,
}

const impl = (
  kind: ModelImpl['kind'],
  name: string,
  label: string,
  description: string,
  data_location: DataLocation,
  data_note: string,
  license: string,
  roles: string[],
  options: ModelOptionField[] = [],
  extra: Partial<ModelImpl> = {},
): ModelImpl => ({ kind, impl: name, label, description, data_location, data_note, license, roles, options, role_defaults: {}, role_notes: {}, requirements: [], ...extra })

export function mockCatalog(downloaded: ReadonlySet<string>): ModelImpl[] {
  const whisperChoices = [
    choice('small', 'small', '가장 가볍고 빠릅니다. 한국어 글자를 자주 틀립니다(노트북 측정 CER 13%).'),
    choice('medium', 'medium', '실시간 권장(정확도 기준, 측정 CER 1%). 노트북 CPU에서 발화 끝부터 확정까지 8~12초 걸립니다.', { recommended_for: ['stt.streaming'] }),
    choice('large-v3', 'large-v3', '사후 권장. 가장 정확합니다(측정 CER 0%). 노트북 CPU에서 30초 녹음에 약 36초, 메모리 3.3GB.', { recommended_for: ['stt.batch'] }),
    choice('large-v3-turbo', 'large-v3-turbo', 'large-v3의 디코더를 줄인 모델. 정확도는 large-v3에 가깝고(CER 0.4%), 인코더가 커서 CPU에서는 medium보다 느립니다.'),
  ].map((c) => ({ ...c, size_bytes: WHISPER_SIZES[c.value] ?? null, downloaded: downloaded.has(c.value) }))
  return [
    impl('llm', 'fake', 'Fake LLM', '자격증명 없이 도는 규칙 기반 응답. 화면과 흐름 확인용이며 내용의 품질은 없습니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['llm.primary', 'llm.screening'], [field('model', '모델 이름 (표시용)', 'string', 'fake-llm', { help: '결과와 감사 로그에 남는 이름입니다.' }), speed], {
      role_defaults: { 'llm.screening': { model: 'fake-llm-screening' } },
    }),
    impl('llm', 'anthropic_vertex', 'Claude (Vertex AI)', '사내 GCP 프로젝트의 Vertex AI로 Claude를 부릅니다.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['llm.primary', 'llm.screening'], [
      field('model', '모델', 'select', 'claude-opus-5-5', {
        choices: [
          choice('claude-opus-5-5', 'Claude Opus 5.5', '주 모델 권장', { recommended_for: ['llm.primary'] }),
          choice('claude-sonnet-5-5', 'Claude Sonnet 5.5', '속도와 성능의 균형'),
          choice('claude-haiku-5-5', 'Claude Haiku 5.5', '선별용 권장 (대량·저비용)', { recommended_for: ['llm.screening'] }),
          choice('claude-fable-5-1', 'Claude Fable 5.1', '가장 높은 성능, 가장 비쌈'),
        ],
      }),
      field('region', '리전', 'string', 'global', { help: 'Vertex AI 엔드포인트 리전 (global 권장).' }),
    ], { role_defaults: { 'llm.screening': { model: 'claude-haiku-5-5' } } }),
    impl('llm', 'anthropic_api', 'Claude API (외부, 모의 예시)', 'Anthropic API를 직접 부르는 예시입니다. 모의 모드에만 있고, 외부 전송 경고 단계를 보여 줍니다.', 'external', '비식별 프롬프트가 회사 밖(Anthropic API)으로 나갑니다.', '상용 (API 과금)', ['llm.primary', 'llm.screening'], [
      field('model', '모델', 'select', 'claude-opus-5-5', { choices: [choice('claude-opus-5-5', 'Claude Opus 5.5'), choice('claude-sonnet-5-5', 'Claude Sonnet 5.5')] }),
    ]),
    impl('stt', 'fake', 'Fake STT', '가상 지원자 대본(텍스트)을 받아 적습니다. 실제 음성은 알아듣지 않고 길이만 알려 줍니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['stt.streaming', 'stt.batch'], [ko, speed, batchDiarization], {
      role_defaults: { 'stt.batch': { diarization: true } },
    }),
    impl('stt', 'faster_whisper', 'Whisper (로컬, faster-whisper)', 'OpenAI Whisper를 이 PC의 CPU에서 돌립니다(int8). 무료, 오프라인, 한국어 고정.', 'local', '음성은 이 PC 밖으로 나가지 않습니다. 모델 파일만 Hugging Face에서 한 번 내려받습니다.', 'MIT (faster-whisper, Whisper 가중치)', ['stt.streaming', 'stt.batch'], [
      field('model', '모델 크기', 'select', 'medium', { choices: whisperChoices }),
      ko,
      field('initial_prompt', '기술 용어 힌트', 'text', '', {
        help: '면접에 자주 나오는 용어·약어·고유명사를 적으면 그 표기로 받아 적을 확률이 높아집니다. 예: 반도체 공정, CMP, 식각, 수율, SPC, Kubernetes. 너무 길면 오히려 엉뚱한 말을 지어낼 수 있으니 짧게 씁니다.',
        max_length: 500,
      }),
      field('beam_size', '빔 크기', 'integer', 5, { help: '클수록 조금 더 정확하고 느립니다. 실시간은 1~2.', minimum: 1, maximum: 5 }),
      field('vad_min_silence_ms', '발화 끝 판정 침묵 (ms)', 'integer', 500, { help: '이만큼 조용하면 한 발화가 끝난 것으로 보고 확정 전사를 냅니다.', minimum: 200, maximum: 2000 }),
      field('cpu_threads', 'CPU 스레드', 'integer', 0, { help: '0이면 자동 (코어 수 - 4).', minimum: 0, maximum: 32 }),
    ], {
      role_defaults: { 'stt.streaming': { model: 'medium', beam_size: 1 }, 'stt.batch': { model: 'large-v3', beam_size: 5 } },
      role_notes: { 'stt.streaming': LIVE_NOTE, 'stt.batch': '화자 구분은 하지 않습니다 (화자분리 역할이 따로 맡습니다).' },
    }),
    impl('stt', 'google_stt_v2', 'Google Speech-to-Text v2', '사내 GCP 프로젝트의 Speech-to-Text v2 (Chirp).', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['stt.streaming', 'stt.batch'], [
      field('model', '모델', 'select', 'chirp_3', { choices: [choice('chirp_3', 'Chirp 3'), choice('chirp_2', 'Chirp 2'), choice('long', 'long')] }),
      ko,
      batchDiarization,
    ], { role_defaults: { 'stt.batch': { diarization: true } }, role_notes: { 'stt.streaming': LIVE_NOTE } }),
    impl('embedding', 'fake', 'Fake 임베딩', '텍스트 해시로 만든 단위 벡터. 차원과 흐름 확인용입니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['embedding'], [
      field('dimensions', '차원', 'integer', 8, { minimum: 2, maximum: 4096 }),
    ]),
    impl('embedding', 'vertex_embedding', 'Vertex AI 임베딩', '사내 GCP 프로젝트의 Vertex AI 텍스트 임베딩.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['embedding'], [
      field('model', '모델', 'select', 'gemini-embedding-001', { choices: [choice('gemini-embedding-001', 'gemini-embedding-001'), choice('text-multilingual-embedding-002', 'text-multilingual-embedding-002')] }),
      field('dimensions', '차원', 'integer', 768, { minimum: 128, maximum: 3072 }),
    ]),
    impl('diarization', 'fake', 'Fake 화자분리', '고정된 화자 구간 두 개를 돌려줍니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['diarization']),
    impl('diarization', 'google_stt_v2', 'Google Speech-to-Text v2 화자분리', '사내 GCP 프로젝트의 Speech-to-Text v2 화자 구분.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['diarization']),
  ]
}

const ok = (key: string, label: string, detail: string): ModelRequirement => ({ key, label, ok: true, detail, fix: null })

/** Mock machine: GCP credentials present (mock world), faster-whisper installed, weights as downloaded. */
export function requirementsFor(i: ModelImpl, options: Record<string, ModelOptionValue>, downloaded: ReadonlySet<string>): ModelRequirement[] {
  const reqs = [ok('implemented', '구현', '구현되어 있습니다.')]
  if (i.data_location === 'gcp') {
    reqs.push(ok('env:GOOGLE_CLOUD_PROJECT', '환경변수 GOOGLE_CLOUD_PROJECT', '설정되어 있습니다.'), ok('gcp_credentials', 'GCP 자격증명', '서비스 계정 키 파일이 있습니다.'))
  }
  if (i.impl === 'anthropic_api') reqs.push(ok('env:ANTHROPIC_API_KEY', '환경변수 ANTHROPIC_API_KEY', '설정되어 있습니다.'))
  if (i.impl === 'faster_whisper') {
    reqs.push(ok('package:faster_whisper', '패키지 faster_whisper', '설치되어 있습니다.'))
    const model = String(options.model ?? '')
    if (model in WHISPER_SIZES) {
      const has = downloaded.has(model)
      const size = (WHISPER_SIZES[model] ?? 0) >= 1e9 ? `${((WHISPER_SIZES[model] ?? 0) / 1e9).toFixed(1)}GB` : `${Math.round((WHISPER_SIZES[model] ?? 0) / 1e6)}MB`
      reqs.push({
        key: `weights:faster-whisper/${model}`,
        label: `모델 파일 ${model}`,
        ok: has,
        detail: has ? '내려받았습니다.' : `아직 내려받지 않았습니다 (${size}).`,
        fix: has ? null : '모델 크기 옆의 다운로드 버튼으로 받습니다.',
      })
    }
  }
  return reqs
}

export class SpecError extends Error {
  readonly field: string

  constructor(field: string, message: string) {
    super(message)
    this.field = field
  }
}

/** Mirrors catalog.validate_options: unknown keys refused, defaults filled, fixed fields unchanged. */
export function normalize(i: ModelImpl, role: string, options: Record<string, ModelOptionValue>): Record<string, ModelOptionValue> {
  const fields = i.options.filter((f) => f.roles.length === 0 || f.roles.includes(role))
  const unknown = Object.keys(options).filter((k) => !fields.some((f) => f.key === k))
  if (unknown.length) throw new SpecError(unknown[0]!, `알 수 없는 옵션입니다: ${unknown.join(', ')}`)
  const values: Record<string, ModelOptionValue> = {}
  for (const f of fields) if (f.default !== null) values[f.key] = f.default
  Object.assign(values, i.role_defaults[role] ?? {})
  for (const f of fields) {
    if (!(f.key in options)) continue
    const v = options[f.key]!
    if (f.fixed) {
      if (v !== values[f.key]) throw new SpecError(f.key, `${f.label}은(는) 바꿀 수 없습니다.`)
      continue
    }
    if (f.type === 'select' && !f.choices.some((c) => c.value === v)) throw new SpecError(f.key, `${f.label}: 고를 수 있는 값이 아닙니다.`)
    if ((f.type === 'integer' || f.type === 'number') && (typeof v !== 'number' || (f.minimum !== null && v < f.minimum) || (f.maximum !== null && v > f.maximum)))
      throw new SpecError(f.key, `${f.label}: 범위를 벗어났습니다.`)
    values[f.key] = typeof v === 'string' ? v.trim() : v
  }
  return values
}

export interface DownloadJob {
  startedAt: number
  durationMs: number
  cancelled: boolean
}

export interface ModelState {
  active: Record<ModelRole, ModelSpec>
  history: ModelChange[]
  downloaded: Set<string>
  downloads: Map<string, DownloadJob>
}

const INITIAL: Record<ModelRole, ModelSpec> = {
  'llm.primary': { impl: 'anthropic_vertex', options: { model: 'claude-opus-5-5', region: 'global' } },
  'llm.screening': { impl: 'anthropic_vertex', options: { model: 'claude-haiku-5-5', region: 'global' } },
  'stt.streaming': { impl: 'google_stt_v2', options: { model: 'chirp_3', language: 'ko-KR' } },
  'stt.batch': { impl: 'google_stt_v2', options: { model: 'chirp_3', language: 'ko-KR', diarization: true } },
  embedding: { impl: 'vertex_embedding', options: { model: 'gemini-embedding-001', dimensions: 768 } },
  diarization: { impl: 'google_stt_v2', options: {} },
}

export function createModelState(now: Date, newId: () => string): ModelState {
  const at = new Date(now.getTime() - 3 * 24 * 3600 * 1000).toISOString()
  const downloaded = new Set<string>()
  const catalog = mockCatalog(downloaded)
  const history = MODEL_ROLES.map((role, i) => ({
    id: newId(),
    revision: i + 1,
    occurred_at: at,
    role,
    role_label: ROLE_INFO[role].label,
    kind: 'initial' as const,
    actor: null,
    previous: null,
    new: structuredClone(INITIAL[role]),
    previous_label: null,
    new_label: specLabel(catalog, role, INITIAL[role]) ?? '',
    reason: 'providers YAML 기본값',
    reverts_change_id: null,
    details: null,
  })).reverse()
  return { active: structuredClone(INITIAL), history, downloaded, downloads: new Map() }
}

export const kindOf = (role: string) => role.split('.')[0] as ModelImpl['kind']

export function findImpl(catalog: ModelImpl[], role: string, name: string) {
  return catalog.find((i) => i.kind === kindOf(role) && i.impl === name)
}

export function specLabel(catalog: ModelImpl[], role: string, spec: ModelSpec | null): string | null {
  if (!spec) return null
  const i = findImpl(catalog, role, spec.impl)
  const model = spec.options.model
  return model ? `${i?.label ?? spec.impl} · ${model}` : (i?.label ?? spec.impl)
}

export function modelName(spec: ModelSpec): string {
  if (spec.impl === 'faster_whisper') return `faster-whisper-${String(spec.options.model ?? 'medium')}`
  if (spec.impl === 'fake') return String(spec.options.model ?? 'fake')
  return String(spec.options.model ?? spec.impl)
}

export function roleState(state: ModelState, role: ModelRole, catalog: ModelImpl[]): ModelRoleState {
  const spec = state.active[role]
  const i = findImpl(catalog, role, spec.impl)!
  const requirements = requirementsFor(i, spec.options, state.downloaded)
  const unmet = requirements.filter((r) => !r.ok).map((r) => r.label)
  return {
    role,
    ...ROLE_INFO[role],
    kind: kindOf(role),
    spec: structuredClone(spec),
    impl_label: i.label,
    model: modelName(spec),
    data_location: i.data_location,
    status: unmet.length ? 'unavailable' : 'ready',
    status_detail: unmet.length ? `요구 조건 미충족: ${unmet.join(', ')}` : null,
    requirements,
    note: i.role_notes[role] ?? null,
    last_change: state.history.find((c) => c.role === role) ?? null,
    pinned_sessions: 0,
  }
}

export function testResult(role: string, spec: ModelSpec, audio: File | null): ModelTestResult {
  const model = modelName(spec)
  const base = { ok: true, model, error: null, audio: null as ModelTestResult['audio'] }
  if (role.startsWith('llm.')) {
    return { ...base, latency_ms: 840, summary: '구조화 출력(JSON)으로 지시대로 답했습니다.', output: { structured: { echo: '모델 연결 확인 문장입니다', sum: 42 }, input_tokens: 61, output_tokens: 18 } }
  }
  if (role === 'embedding') {
    const dims = Number(spec.options.dimensions ?? 768)
    return { ...base, latency_ms: 120, summary: `${dims}차원 벡터 2개를 받았습니다.`, output: { vectors: 2, dimensions: dims, expected_dimensions: dims } }
  }
  if (role === 'diarization') {
    return { ...base, audio: audio ? 'upload' : 'sample', latency_ms: 950, summary: '화자 2명, 구간 2개를 받았습니다.', output: { turns: 2, speakers: ['SPEAKER_1', 'SPEAKER_2'] } }
  }
  const seconds = audio ? Math.max(1, Math.round((audio.size / 16_000) * 10) / 10) : 11.46
  const fake = spec.impl === 'fake'
  const text = fake
    ? `[fake 전사] 오디오 ${seconds.toFixed(1)}초 (fake STT는 음성을 알아듣지 않습니다)`
    : audio
      ? '[모의 전사] 모의 모드는 음성을 알아듣지 않습니다. 실제 결과는 백엔드 연결 모드에서 확인하세요.'
      : SAMPLE_TEXT
  const latency = fake ? 40 : spec.impl === 'faster_whisper' ? Math.round(seconds * 650) : 1300
  const output: Record<string, unknown> = { audio_seconds: seconds, text, realtime_factor: Math.round((latency / 1000 / seconds) * 1000) / 1000 }
  if (!audio) Object.assign(output, { expected_text: SAMPLE_TEXT, cer: fake ? 1 : 0 })
  if (role === 'stt.streaming') Object.assign(output, { partials: fake ? 0 : 3, finals: 1, first_result_ms: latency })
  return { ...base, audio: audio ? 'upload' : 'sample', latency_ms: latency, summary: `${seconds.toFixed(1)}초 음성을 전사했습니다.`, output }
}
