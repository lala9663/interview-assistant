/**
 * Mock 관리자 > 모델 설정: the catalog (mirrors `providers/catalog.py`), the active spec per role, the change
 * history, simulated weight downloads and connection tests. The mock world runs `config/providers.yaml`
 * (the LLM on an in-house vLLM server, Chirp STT on Google Cloud) as if both were reachable, so the screen
 * shows every data location; `anthropic_api` exists only here, to show the external-transfer warning.
 */
import type {
  DataLocation,
  ModelChange,
  ModelGroup,
  ModelImpl,
  ModelOptionField,
  ModelOptionValue,
  ModelRequirement,
  ModelRole,
  ModelRoleState,
  ModelSpec,
  ModelTestResult,
} from '@/api/types'
import { MODEL_ROLE_KIND, MODEL_ROLES } from '@/api/types'

export const ROLE_INFO: Record<ModelRole, { label: string; description: string; group?: ModelGroup }> = {
  'llm.primary': { label: 'LLM 주 모델', description: '역량 사전 초안, 꼬리질문, AI 채점' },
  'llm.screening': { label: 'LLM 선별용', description: '서류 구조화와 선별' },
  'stt.streaming': { label: 'STT 실시간', description: '면접 중 지원자 답변 전사' },
  'stt.batch': { label: 'STT 사후', description: '녹음 파일 전사 (10단계)' },
  embedding: { label: '임베딩', description: '질문 은행 검색, 같은 질문 거르기, 비슷한 역량 사전·평점 기준 찾기' },
  diarization: { label: '화자분리', description: '대면 면접 화자 구분 (10단계)' },
  'document.reading': { label: '읽기 방식', description: '텍스트 층과 OCR 중 무엇으로 읽을지, 문서 속 그림', group: 'documents' },
  'document.ocr': { label: 'OCR 엔진', description: '스캔본·사진·그림 속 글자 읽기', group: 'documents' },
  'document.pdf': { label: 'PDF 텍스트 추출', description: 'PDF의 텍스트 층 읽기', group: 'documents' },
  'document.hwp': { label: 'HWP·HWPX 읽기', description: '한글 문서 (HWP 5.x, HWPX)', group: 'documents' },
  'document.legacy': { label: '구형 오피스 변환', description: '.doc·.ppt를 .docx·.pptx로 바꿔 읽기', group: 'documents' },
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
const GCP_NOTE = '회사 밖 Google Cloud로 데이터를 보냅니다. GCP는 쓰지 않기로 해서(2026-10-28) 비교용으로만 남긴 대안입니다.'
/** The in-house model server of the mock world (config/providers.yaml). */
export const SERVER_URL = 'http://vllm.internal:8000/v1'
export const SERVER_MODEL = 'skt/A.X-3.1'
const OPENAI_HOST = /(^|\.)openai\.com$|\.openai\.azure\.com$/i
const LIVE_NOTE =
  '실시간 면접의 음성 입력(마이크·WebRTC)은 다음 단계에서 붙습니다. 그 전까지 진행 중 면접 화면은 가상 지원자 대본(텍스트)을 보내므로, fake가 아닌 STT로 바꾸면 새로 시작하는 면접의 전사가 꺼지고 수기 답변 입력으로 바뀝니다. 지금 진행 중인 면접은 시작할 때의 STT를 계속 씁니다.'

export const WHISPER_SIZES: Record<string, number> = {
  small: 486_212_372,
  medium: 1_530_571_735,
  'large-v3': 3_090_835_702,
  'large-v3-turbo': 1_621_665_983,
}

/** Downloadable model files per implementation: impl -> model choice -> bytes. */
export const WEIGHT_SIZES: Record<string, Record<string, number>> = {
  faster_whisper: WHISPER_SIZES,
  paddleocr: { 'ppocrv5-mobile': 32_288_476, 'ppocrv5-server': 115_701_129 },
  tesseract: { best: 27_928_729, fast: 5_790_503 },
  bge_m3: { 'bge-m3': 2_284_631_868 },
}
export const weightKey = (impl: string, model: string) => `${impl}:${model}`
const LOCAL_FILES = '서류와 그림은 이 PC 밖으로 나가지 않습니다.'
const NO_LLM_IMAGES = '그림은 OCR로 글자만 읽고 버립니다. LLM에는 그림을 보내지 않습니다.'

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

const retrieval = (sparse: number, duplicate: number, minimum: number) => [
  field('sparse_weight', '단어 일치 가중치', 'number', sparse, {
    help: '검색 점수 = 의미 유사도 + 이 값 × 단어 일치 점수. 전문 용어·약어(FDC, RF, CVD)가 그대로 맞는 질문을 끌어올립니다. 0이면 의미만 봅니다.',
    minimum: 0,
    maximum: 1,
  }),
  field('duplicate_threshold', '같은 질문으로 볼 유사도', 'number', duplicate, {
    help: '꼬리질문 후보가 이 면접이나 이전 차수에서 이미 한 질문과 의미 유사도가 이 값 이상이면 뺍니다. 낮출수록 더 많이 거릅니다.',
    minimum: 0.5,
    maximum: 1,
  }),
  field('min_score', '질문 은행 제안 최소 점수', 'number', minimum, { help: '답변과의 검색 점수가 이보다 낮은 질문 은행 질문은 제안하지 않습니다.', minimum: 0, maximum: 2 }),
]

export function mockCatalog(downloaded: ReadonlySet<string>): ModelImpl[] {
  const whisperChoices = [
    choice('small', 'small', '가장 가볍고 빠릅니다. 한국어 글자를 자주 틀립니다(노트북 측정 CER 13%).'),
    choice('medium', 'medium', '실시간 권장(정확도 기준, 측정 CER 1%). 노트북 CPU에서 발화 끝부터 확정까지 8~12초 걸립니다.', { recommended_for: ['stt.streaming'] }),
    choice('large-v3', 'large-v3', '사후 권장. 가장 정확합니다(측정 CER 0%). 노트북 CPU에서 30초 녹음에 약 36초, 메모리 3.3GB.', { recommended_for: ['stt.batch'] }),
    choice('large-v3-turbo', 'large-v3-turbo', 'large-v3의 디코더를 줄인 모델. 정확도는 large-v3에 가깝고(CER 0.4%), 인코더가 커서 CPU에서는 medium보다 느립니다.'),
  ].map((c) => ({ ...c, size_bytes: WHISPER_SIZES[c.value] ?? null, downloaded: downloaded.has(weightKey('faster_whisper', c.value)) }))
  const sized = (name: string, choices: ReturnType<typeof choice>[]) =>
    choices.map((c) => ({ ...c, size_bytes: WEIGHT_SIZES[name]?.[c.value] ?? null, downloaded: downloaded.has(weightKey(name, c.value)) }))
  return [
    impl('llm', 'fake', 'Fake LLM', '자격증명 없이 도는 규칙 기반 응답. 화면과 흐름 확인용이며 내용의 품질은 없습니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['llm.primary', 'llm.screening'], [field('model', '모델 이름 (표시용)', 'string', 'fake-llm', { help: '결과와 감사 로그에 남는 이름입니다.' }), speed], {
      role_defaults: { 'llm.screening': { model: 'fake-llm-screening' } },
    }),
    impl(
      'llm',
      'open_model_server',
      '오픈소스 모델 서버 (vLLM·Ollama 등)',
      '사내에 설치한 오픈 웨이트 모델 서버(vLLM, Ollama, SGLang 등)를 부릅니다. 이런 서버가 주는 OpenAI 형식 API(/v1/chat/completions)를 쓰지만 OpenAI 서비스로는 보내지 않습니다(openai.com 주소는 거부). 도구 호출은 쓰지 않습니다.',
      'server',
      '비식별 텍스트만 관리자가 적은 사내 서버 주소로 보냅니다. 회사 밖 주소를 적으면 안 됩니다. 프롬프트와 응답은 저장하지 않고, 감사 로그에는 호출 기록만 남습니다.',
      '모델마다 다름 (docs/reference/llm.md)',
      ['llm.primary', 'llm.screening'],
      [
        field('base_url', '서버 주소', 'string', '', {
          help: '모델 서버의 OpenAI 형식 API 주소를 /v1까지 적습니다. 예: vLLM http://10.0.0.5:8000/v1, Ollama http://10.0.0.5:11434/v1. openai.com 주소는 받지 않습니다.',
          max_length: 300,
        }),
        field('model', '모델 이름', 'string', '', {
          help: '서버에 올린 이름 그대로 적습니다. vLLM은 --served-model-name(없으면 Hugging Face 경로, 예: Qwen/Qwen3-8B), Ollama는 qwen3:8b처럼 태그까지.',
          max_length: 200,
        }),
        field('api_key_env', 'API 키 환경변수 이름', 'string', '', {
          help: '서버가 키를 요구하면 키가 든 환경변수의 이름을 적습니다(예: IA_LLM_API_KEY). 키 값은 여기에 적지 않고 서버 환경에만 둡니다. 비우면 키 없이 부릅니다.',
        }),
        field('timeout', '타임아웃 (초)', 'number', 120, { help: '요청 하나를 기다리는 최대 시간. 스트리밍은 토큰 사이 간격에 적용합니다. GPU 없는 서버라면 늘립니다.', minimum: 5, maximum: 600 }),
        field('max_tokens', '최대 출력 토큰', 'integer', 4096, {
          help: '요청마다 앱이 정한 값과 이 값 중 작은 쪽을 씁니다. 서버의 컨텍스트 길이(vLLM --max-model-len, Ollama num_ctx)에서 입력 길이를 뺀 것보다 작아야 합니다.',
          minimum: 256,
          maximum: 32768,
        }),
        field('temperature', '온도', 'number', 0.3, { help: '낮을수록 같은 입력에 같은 답을 냅니다. AI 채점은 한 답변을 세 번 채점해 중앙값을 쓰므로 0보다 조금 큰 값을 권합니다.', minimum: 0, maximum: 2 }),
        field('structured_output', '구조화 출력 방식', 'select', 'json_schema', {
          help: '채점·선별처럼 JSON으로 받는 작업에서 서버에 형식을 어떻게 요구할지. 스키마는 어느 방식이든 프롬프트에도 넣습니다.',
          choices: [
            choice('json_schema', 'JSON 스키마 강제', 'vLLM·SGLang·Ollama가 스키마에 맞는 JSON만 만듭니다.', { recommended_for: ['llm.primary', 'llm.screening'] }),
            choice('json_object', 'JSON만 강제', '스키마 강제를 못 하는 서버·게이트웨이용.'),
            choice('prompt', '프롬프트로만 요청', '서버가 response_format을 거부할 때.'),
          ],
        }),
        field('headers', '추가 헤더 (사내 게이트웨이용)', 'text', '', {
          help: "한 줄에 '이름: 값' 하나. 키·토큰은 값 대신 ${환경변수}로 적습니다 (예: X-Gateway-Key: ${IA_GATEWAY_KEY}). 값은 서버 환경에서 읽고 저장하지 않습니다.",
          max_length: 1000,
        }),
        field('extra_body', '추가 요청 필드 (JSON)', 'text', '', {
          help: '서버별 옵션을 요청에 더합니다. 예: vLLM에서 Qwen3의 추론 끄기 {"chat_template_kwargs": {"enable_thinking": false}}. model·messages·tools 같은 필드는 넣을 수 없습니다.',
          max_length: 2000,
        }),
      ],
    ),
    impl('llm', 'anthropic_vertex', 'Claude (Vertex AI)', 'Google Cloud의 Vertex AI로 Claude를 부릅니다. GCP를 쓰지 않기로 해서 구현하지 않은 대안입니다.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['llm.primary', 'llm.screening'], [
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
    impl('stt', 'google_stt_v2', 'Google Speech-to-Text v2', 'Google Cloud의 Speech-to-Text v2 (Chirp). 구현 전이며 비교 대상입니다.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['stt.streaming', 'stt.batch'], [
      field('model', '모델', 'select', 'chirp_3', { choices: [choice('chirp_3', 'Chirp 3'), choice('chirp_2', 'Chirp 2'), choice('long', 'long')] }),
      ko,
      batchDiarization,
    ], { role_defaults: { 'stt.batch': { diarization: true } }, role_notes: { 'stt.streaming': LIVE_NOTE } }),
    impl('embedding', 'fake', 'Fake 임베딩', '단어와 두 글자 조각을 해시해 만든 벡터. 같은 단어를 쓴 문장끼리만 가깝고 뜻은 모릅니다. 흐름 확인용입니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['embedding'], [
      field('dimensions', '차원', 'integer', 256, { minimum: 2, maximum: 4096 }),
      ...retrieval(0.3, 0.8, 0.15),
    ]),
    impl(
      'embedding',
      'bge_m3',
      'BGE-M3 (로컬)',
      'BAAI의 다국어 임베딩 모델을 이 PC의 CPU에서 돌립니다(ONNX Runtime). 의미 벡터(1024차원)와 단어 일치 가중치를 함께 내어, 뜻이 비슷한 질문과 전문 용어·약어가 맞는 질문을 같이 찾습니다. 무료, 오프라인.',
      'local',
      '질문·답변 텍스트는 이 PC 밖으로 나가지 않습니다. 모델 파일만 Hugging Face에서 한 번 내려받습니다.',
      'MIT (BGE-M3 모델, ONNX Runtime), Apache-2.0 (tokenizers)',
      ['embedding'],
      [
        field('model', '모델', 'select', 'bge-m3', {
          choices: sized('bge_m3', [
            choice('bge-m3', 'BGE-M3 (fp32 ONNX)', '한국어 포함 100여 개 언어, 최대 8,192토큰. 밀집 1024차원 + 희소(단어 일치). 메모리 약 2.5GB.', { recommended_for: ['embedding'] }),
          ]),
        }),
        field('max_length', '최대 길이 (토큰)', 'integer', 512, { help: '이보다 긴 텍스트는 잘라서 임베딩합니다. 면접 답변 하나는 보통 300토큰 안쪽이고, 길수록 느려집니다.', minimum: 64, maximum: 8192 }),
        field('cpu_threads', 'CPU 스레드', 'integer', 0, { help: '0이면 자동 (코어 수의 절반, 최대 6).', minimum: 0, maximum: 32 }),
        ...retrieval(0.3, 0.85, 0.55),
      ],
    ),
    impl('embedding', 'vertex_embedding', 'Vertex AI 임베딩', 'Google Cloud의 Vertex AI 텍스트 임베딩. 구현 전이며 비교 대상입니다.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['embedding'], [
      field('model', '모델', 'select', 'gemini-embedding-001', { choices: [choice('gemini-embedding-001', 'gemini-embedding-001'), choice('text-multilingual-embedding-002', 'text-multilingual-embedding-002')] }),
      field('dimensions', '차원', 'integer', 768, { minimum: 128, maximum: 3072 }),
    ]),
    impl('diarization', 'fake', 'Fake 화자분리', '고정된 화자 구간 두 개를 돌려줍니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['diarization']),
    impl('diarization', 'google_stt_v2', 'Google Speech-to-Text v2 화자분리', 'Google Cloud의 Speech-to-Text v2 화자 구분. 구현 전이며 비교 대상입니다.', 'gcp', GCP_NOTE, '상용 (GCP 과금)', ['diarization']),
    // 서류 읽기
    impl('reading', 'standard', '읽기 방식', '페이지(슬라이드)마다 텍스트 층을 쓸지 OCR로 읽을지 정합니다. 깨진 텍스트 층은 보내지 않습니다.', 'local', '설정입니다. 데이터를 보내지 않습니다.', '프로젝트 코드', ['document.reading'], [
      field('mode', '읽기 방식', 'select', 'auto', {
        help: '자동: 텍스트 층이 있으면 텍스트, 없거나 깨졌으면 OCR. 항상 OCR: PDF 쪽과 그림을 모두 OCR (문서 속성·숨은 텍스트·링크는 그대로 읽음). 텍스트만: OCR 없이, 텍스트 층 없는 쪽이 있으면 보류.',
        choices: [choice('auto', '자동 (텍스트 우선, 없거나 깨지면 OCR)', '', { recommended_for: ['document.reading'] }), choice('always_ocr', '항상 OCR'), choice('text_only', '텍스트만 (OCR 안 함)')],
      }),
      field('embedded_images', '문서 속 그림 OCR', 'boolean', true, { help: 'DOCX·PPTX·HWP·PDF 안의 그림(자격증 사본, 캡처 화면)을 OCR로 읽습니다. 증명사진으로 보이는 그림은 이 설정과 관계없이 읽지 않고 버립니다.' }),
      field('sensitivity', '깨짐 판정 민감도', 'select', 'medium', {
        help: "텍스트 층이 깨졌다고(글꼴 매핑 문제로 'ÀÌ·Â¼­'처럼 나옴) 볼 기준. 깨진 쪽은 OCR로 다시 읽습니다.",
        choices: [choice('low', '낮음 (의심 글자 30% 이상)'), choice('medium', '보통 (15% 이상 또는 3글자 연속)', '', { recommended_for: ['document.reading'] }), choice('high', '높음 (5% 이상 또는 2글자 연속)')],
      }),
      field('dpi', 'OCR 해상도 (dpi)', 'integer', 200, { help: 'PDF 쪽을 그림으로 바꿀 해상도.', minimum: 100, maximum: 400 }),
      field('low_confidence', 'OCR 신뢰도 경고 기준', 'number', 0.8, { help: 'OCR 평균 신뢰도가 이보다 낮은 쪽은 검토 리포트에 경고로 남깁니다 (0~1).', minimum: 0, maximum: 1 }),
    ]),
    impl('ocr', 'fake', 'Fake OCR', '글자를 읽지 않고 자리 표시 한 줄만 돌려줍니다. 화면과 흐름 확인용입니다.', 'local', '외부 호출이 없습니다.', '프로젝트 코드', ['document.ocr']),
    impl('ocr', 'paddleocr', 'PaddleOCR (로컬, PP-OCRv5 한국어)', '이 PC의 CPU에서 PP-OCRv5로 읽습니다. 무료, 오프라인. 한국어·영문·숫자.', 'local', `${LOCAL_FILES} 모델 파일만 Hugging Face에서 한 번 내려받습니다. ${NO_LLM_IMAGES}`, 'Apache-2.0 (PaddleOCR, PaddlePaddle, PP-OCRv5 모델)', ['document.ocr'], [
      field('model', '모델', 'select', 'ppocrv5-mobile', {
        choices: sized('paddleocr', [
          choice('ppocrv5-mobile', 'PP-OCRv5 mobile + 한국어 인식', '권장. 이 노트북 CPU에서 A4 한 쪽 2~7초, 메모리 최대 약 1.6GB.', { recommended_for: ['document.ocr'] }),
          choice('ppocrv5-server', 'PP-OCRv5 server + 한국어 인식', '검출 모델이 큽니다. 이 노트북 CPU에서 한 쪽 30초 이상, 메모리 약 2.9GB. GPU 서버용.'),
        ]),
      }),
      field('textline_orientation', '줄 방향 보정', 'boolean', false, { help: '뒤집힌 줄을 바로 세웁니다. 바로 선 스캔에서 멀쩡한 줄을 뒤집어 망치는 일이 있어 기본은 끔.' }),
      field('doc_orientation', '쪽 방향 보정', 'boolean', false, { help: '90°·180° 돌아간 사진을 바로 세웁니다. 옆으로 찍은 휴대폰 사진이 많으면 켭니다.' }),
      field('max_side', '그림 긴 변 제한 (px)', 'integer', 2400, { help: '큰 사진은 줄여서 읽습니다.', minimum: 1200, maximum: 4000 }),
      field('cpu_threads', 'CPU 스레드', 'integer', 0, { help: '0이면 자동 (코어 수 - 4).', minimum: 0, maximum: 32 }),
    ]),
    impl('ocr', 'tesseract', 'Tesseract (로컬, 비교용)', '이 PC의 Tesseract 5로 읽습니다. 가볍고 빠르지만 한국어는 음절을 띄어 읽는 등 PaddleOCR보다 부정확합니다.', 'local', `${LOCAL_FILES} 언어 데이터만 GitHub에서 한 번 내려받습니다. ${NO_LLM_IMAGES}`, 'Apache-2.0 (Tesseract, tessdata)', ['document.ocr'], [
      field('model', '언어 데이터', 'select', 'best', {
        choices: sized('tesseract', [choice('best', 'tessdata_best (kor+eng)', '정확도 우선 LSTM 모델.'), choice('fast', 'tessdata_fast (kor+eng)', '빠르고 작은 모델. 한국어 정확도는 더 낮습니다.')]),
      }),
      field('psm', '페이지 분할 방식 (psm)', 'integer', 3, { help: '3 자동, 4 한 단, 6 한 덩어리 글.', minimum: 3, maximum: 13 }),
    ]),
    impl('ocr', 'google_document_ai', 'Google Document AI (외부 클라우드)', 'Google Cloud의 Document AI OCR. 구현 전이며 비교 대상입니다. 처리 위치는 프로세서의 리전(us·eu)입니다.', 'gcp', '서류 그림(이름·연락처가 그대로 보이는 원본 쪽)을 회사 밖 Google Cloud의 Document AI로 보냅니다.', '상용 (GCP 과금)', ['document.ocr'], [
      field('processor_id', '프로세서 ID', 'string', 'ocr-processor', { help: 'Document AI OCR 프로세서.' }),
      field('location', '위치', 'string', 'us', { help: '프로세서 리전 (us 또는 eu).' }),
    ]),
    impl('ocr', 'clova_ocr', 'Naver CLOVA OCR (외부)', '네이버 클라우드의 CLOVA OCR. 구현 전이며 비교 대상입니다.', 'external', '서류 그림(이름·연락처가 그대로 보이는 원본 쪽)을 회사 밖 네이버 클라우드로 보냅니다.', '상용 (네이버 클라우드 과금)', ['document.ocr']),
    impl('pdf_reader', 'pdfplumber', 'pdfplumber', '본문·표·숨은 텍스트·주석·링크·속성을 읽고 자간을 되돌립니다. 텍스트 층 없는 쪽과 깨진 쪽을 가려냅니다.', 'local', LOCAL_FILES, 'MIT (pdfplumber, pdfminer.six), Apache-2.0/BSD-3 (pypdfium2)', ['document.pdf'], [
      field('min_text_chars', '텍스트 층 최소 글자 수', 'integer', 30, { help: '한 쪽의 글자가 이보다 적고 그림이 쪽 대부분을 덮으면 텍스트 층이 없는 쪽(스캔)으로 봅니다.', minimum: 5, maximum: 500 }),
    ]),
    impl('hwp_reader', 'syhwp', 'syhwp + OWPML (파이썬)', 'HWP 5.x는 syhwp(MIT)로 열고 머리글·각주·숨은 설명을 나눠 읽습니다. HWPX는 자체 OWPML 읽기. 문서 정보·미리보기 텍스트·흰 글씨(HWPX)까지 읽고, 암호 걸린 문서는 거부합니다.', 'local', LOCAL_FILES, 'MIT (syhwp), BSD (olefile)', ['document.hwp']),
    impl('hwp_reader', 'hwplib', 'hwplib (Java)', 'neolord0의 hwplib·hwpxlib(Apache-2.0)으로 읽는 대안 경로. 구현 전입니다. 실제 한글 샘플에서 syhwp가 부족하면 검토합니다.', 'local', LOCAL_FILES, 'Apache-2.0 (hwplib, hwpxlib)', ['document.hwp']),
    impl('office_converter', 'libreoffice', 'LibreOffice (헤드리스)', '구형 .doc·.ppt를 .docx·.pptx로 바꾼 뒤 같은 방식으로 읽습니다. 매번 임시 프로필로 돌리고 매크로는 실행하지 않습니다.', 'local', LOCAL_FILES, 'MPL-2.0 (LibreOffice, 별도 프로그램으로 실행)', ['document.legacy'], [
      field('timeout', '변환 제한 시간 (초)', 'integer', 120, { minimum: 30, maximum: 600 }),
    ]),
  ]
}

const missing = (key: string, label: string, detail: string, fix: string): ModelRequirement => ({ key, label, ok: false, detail, fix })

const ok = (key: string, label: string, detail: string): ModelRequirement => ({ key, label, ok: true, detail, fix: null })

/** Mock machine: GCP credentials present (mock world), faster-whisper installed, weights as downloaded, every environment variable set. */
export function requirementsFor(i: ModelImpl, options: Record<string, ModelOptionValue>, downloaded: ReadonlySet<string>): ModelRequirement[] {
  const notYet = ['google_document_ai', 'clova_ocr', 'hwplib']
  if (notYet.includes(i.impl)) {
    const reqs = [missing('implemented', '구현', '아직 구현되지 않았습니다.', '이 provider의 구현 단계(구현 순서 문서)를 마친 뒤 쓸 수 있습니다.')]
    if (i.impl === 'clova_ocr')
      reqs.push(
        missing('env:CLOVA_OCR_INVOKE_URL', '환경변수 CLOVA_OCR_INVOKE_URL', '설정되어 있지 않습니다.', '서버를 띄우는 환경(또는 Secret Manager)에 설정합니다. 화면에서는 입력받지 않습니다.'),
        missing('env:CLOVA_OCR_SECRET', '환경변수 CLOVA_OCR_SECRET', '설정되어 있지 않습니다.', '서버를 띄우는 환경(또는 Secret Manager)에 설정합니다. 화면에서는 입력받지 않습니다.'),
      )
    if (i.impl === 'google_document_ai')
      reqs.push(missing('env:DOCUMENT_AI_PROCESSOR_ID', '환경변수 DOCUMENT_AI_PROCESSOR_ID', '설정되어 있지 않습니다.', '서버를 띄우는 환경(또는 Secret Manager)에 설정합니다. 화면에서는 입력받지 않습니다.'))
    if (i.impl === 'hwplib') reqs.push(missing('program:java', '프로그램 Java', '설치되어 있지 않습니다.', 'JRE 8 이상을 설치합니다 (hwplib 경로를 구현할 때만 필요).'))
    return reqs
  }
  const reqs = [ok('implemented', '구현', '구현되어 있습니다.')]
  if (i.impl === 'paddleocr') reqs.push(ok('package:paddleocr', '패키지 paddleocr', '설치되어 있습니다.'), ok('package:paddle', '패키지 paddle', '설치되어 있습니다.'))
  if (i.impl === 'tesseract') reqs.push(ok('program:tesseract', '프로그램 Tesseract', 'tesseract v5.4.0.20240606'))
  if (i.impl === 'libreoffice') reqs.push(ok('program:soffice', '프로그램 LibreOffice', 'LibreOffice 26.8.1.1'))
  if (i.impl === 'bge_m3') reqs.push(ok('package:onnxruntime', '패키지 onnxruntime', '설치되어 있습니다.'), ok('package:tokenizers', '패키지 tokenizers', '설치되어 있습니다.'))
  if (i.impl === 'syhwp') reqs.push(ok('package:syhwp', '패키지 syhwp', '설치되어 있습니다.'), ok('package:olefile', '패키지 olefile', '설치되어 있습니다.'))
  const sizes = WEIGHT_SIZES[i.impl]
  if (sizes && i.impl !== 'faster_whisper') {
    const model = String(options.model ?? '')
    if (model in sizes) {
      const has = downloaded.has(weightKey(i.impl, model))
      reqs.push({
        key: `weights:${i.impl}/${model}`,
        label: `모델 파일 ${model}`,
        ok: has,
        detail: has ? '내려받았습니다.' : `아직 내려받지 않았습니다 (${Math.round((sizes[model] ?? 0) / 1e6)}MB).`,
        fix: has ? null : '모델 옆의 다운로드 버튼으로 받습니다.',
      })
    }
  }
  if (i.data_location === 'gcp') {
    reqs.push(ok('env:GOOGLE_CLOUD_PROJECT', '환경변수 GOOGLE_CLOUD_PROJECT', '설정되어 있습니다.'), ok('gcp_credentials', 'GCP 자격증명', '서비스 계정 키 파일이 있습니다.'))
  }
  if (i.impl === 'anthropic_api') reqs.push(ok('env:ANTHROPIC_API_KEY', '환경변수 ANTHROPIC_API_KEY', '설정되어 있습니다.'))
  if (i.impl === 'open_model_server') {
    reqs.push(ok('package:httpx2', '패키지 httpx2', '설치되어 있습니다.'))
    const env = String(options.api_key_env ?? '').trim()
    if (env) reqs.push(ok(`env:${env}`, `환경변수 ${env}`, '설정되어 있습니다.'))
  }
  if (i.impl === 'faster_whisper') {
    reqs.push(ok('package:faster_whisper', '패키지 faster_whisper', '설치되어 있습니다.'))
    const model = String(options.model ?? '')
    if (model in WHISPER_SIZES) {
      const has = downloaded.has(weightKey('faster_whisper', model))
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
  if (i.impl === 'open_model_server') checkServer(values)
  return values
}

/** Mirrors open_model_server.check_options for the fields the screen most often gets wrong. */
function checkServer(values: Record<string, ModelOptionValue>) {
  const url = String(values.base_url ?? '').replace(/\/+$/, '')
  if (!url) throw new SpecError('base_url', '서버 주소를 적어 주세요 (예: http://10.0.0.5:8000/v1).')
  const parsed = URL.canParse(url) ? new URL(url) : null
  if (!parsed || (parsed.protocol !== 'http:' && parsed.protocol !== 'https:'))
    throw new SpecError('base_url', 'http:// 또는 https://로 시작하는 주소를 적어 주세요 (예: http://10.0.0.5:8000/v1).')
  if (OPENAI_HOST.test(parsed.hostname.replace(/\.$/, ''))) throw new SpecError('base_url', 'OpenAI 서비스 주소는 쓸 수 없습니다. 사내에 설치한 모델 서버의 주소를 적어 주세요.')
  values.base_url = url
  if (!String(values.model ?? '').trim()) throw new SpecError('model', '서버에 올린 모델 이름을 적어 주세요.')
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
  'llm.primary': { impl: 'open_model_server', options: { base_url: SERVER_URL, model: SERVER_MODEL } },
  'llm.screening': { impl: 'open_model_server', options: { base_url: SERVER_URL, model: SERVER_MODEL } },
  'stt.streaming': { impl: 'google_stt_v2', options: { model: 'chirp_3', language: 'ko-KR' } },
  'stt.batch': { impl: 'google_stt_v2', options: { model: 'chirp_3', language: 'ko-KR', diarization: true } },
  embedding: { impl: 'bge_m3', options: { model: 'bge-m3', max_length: 512, cpu_threads: 0, sparse_weight: 0.3, duplicate_threshold: 0.85, min_score: 0.55 } },
  diarization: { impl: 'google_stt_v2', options: {} },
  'document.reading': { impl: 'standard', options: { mode: 'auto', embedded_images: true, sensitivity: 'medium', dpi: 200, low_confidence: 0.8 } },
  'document.ocr': { impl: 'paddleocr', options: { model: 'ppocrv5-mobile', textline_orientation: false, doc_orientation: false, max_side: 2400, cpu_threads: 0 } },
  'document.pdf': { impl: 'pdfplumber', options: { min_text_chars: 30 } },
  'document.hwp': { impl: 'syhwp', options: {} },
  'document.legacy': { impl: 'libreoffice', options: { timeout: 120 } },
}

export function createModelState(now: Date, newId: () => string): ModelState {
  const at = new Date(now.getTime() - 3 * 24 * 3600 * 1000).toISOString()
  // the PoC OCR and embedding are set up
  const downloaded = new Set<string>([weightKey('paddleocr', 'ppocrv5-mobile'), weightKey('bge_m3', 'bge-m3')])
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

export const kindOf = (role: string): ModelImpl['kind'] => MODEL_ROLE_KIND[role as ModelRole] ?? (role.split('.')[0] as ModelImpl['kind'])

export function findImpl(catalog: ModelImpl[], role: string, name: string) {
  return catalog.find((i) => i.kind === kindOf(role) && i.impl === name)
}

const MODE_LABEL: Record<string, string> = { auto: '자동', always_ocr: '항상 OCR', text_only: '텍스트만' }

export function specLabel(catalog: ModelImpl[], role: string, spec: ModelSpec | null): string | null {
  if (!spec) return null
  const i = findImpl(catalog, role, spec.impl)
  const model = spec.options.model ?? MODE_LABEL[String(spec.options.mode)] // 읽기 방식: its mode
  return model ? `${i?.label ?? spec.impl} · ${model}` : (i?.label ?? spec.impl)
}

export function modelName(spec: ModelSpec, role = ''): string {
  if (spec.impl === 'faster_whisper') return `faster-whisper-${String(spec.options.model ?? 'medium')}`
  if (spec.impl === 'standard')
    return `${MODE_LABEL[String(spec.options.mode ?? 'auto')]} · 그림 OCR ${spec.options.embedded_images === false ? '끔' : '켬'} · 깨짐 판정 ${String(spec.options.sensitivity ?? 'medium')}`
  if (spec.impl === 'paddleocr') return `PP-OCRv5 ${String(spec.options.model ?? 'ppocrv5-mobile').replace('ppocrv5-', '')} 한국어`
  if (spec.impl === 'tesseract') return `Tesseract kor+eng (${String(spec.options.model ?? 'best')})`
  if (spec.impl === 'pdfplumber') return 'pdfplumber 0.11.10'
  if (spec.impl === 'syhwp') return 'syhwp + OWPML'
  if (spec.impl === 'libreoffice') return 'LibreOffice (headless)'
  if (spec.impl === 'fake' && role === 'document.ocr') return 'fake-ocr'
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
    group: ROLE_INFO[role].group ?? 'ai',
    spec: structuredClone(spec),
    impl_label: i.label,
    model: modelName(spec, role),
    data_location: i.data_location,
    status: unmet.length ? 'unavailable' : 'ready',
    status_detail: unmet.length ? `요구 조건 미충족: ${unmet.join(', ')}` : null,
    requirements,
    note: i.role_notes[role] ?? null,
    last_change: state.history.find((c) => c.role === role) ?? null,
    pinned_sessions: 0,
  }
}

/** A 서류 읽기 test in the mock: canned page decisions and a de-identified preview (no reading). */
function readingTest(role: string, spec: ModelSpec, document: File | null, model: string): ModelTestResult {
  const mode = String(spec.options.mode ?? 'auto')
  const ocrTool = spec.impl === 'tesseract' ? 'Tesseract 5.4.0 · tessdata_best kor+eng' : spec.impl === 'fake' ? 'fake OCR' : 'PaddleOCR 3.7.0 · PP-OCRv5_mobile_det + korean_PP-OCRv5_mobile_rec'
  const held = role === 'document.reading' && mode === 'text_only'
  const pages = [
    { page: 1, method: 'text', reason: null, tool: 'pdfplumber 0.11.10', confidence: null, elapsed_ms: null, text_chars: 164 },
    held
      ? { page: 2, method: 'held', reason: '텍스트 층 없음, 텍스트만 읽기 설정이라 보류', tool: null, confidence: null, elapsed_ms: null, text_chars: 0 }
      : { page: 2, method: 'ocr', reason: '텍스트 층 없음', tool: ocrTool, confidence: 0.933, elapsed_ms: 2764, text_chars: 0 },
  ]
  const base = { model, error: null, audio: null, document: (document ? 'upload' : 'sample') as ModelTestResult['document'] }
  const output: Record<string, unknown> = {
    format: 'pdf',
    pages,
    images: [
      { label: '1쪽 그림 1', decision: 'photo', confidence: null, detail: '420×560px, 가로세로 0.75, 바탕 58%·글자색 0.0%·중간 42%, 쪽 면적의 2%' },
      { label: '1쪽 그림 2', decision: held || spec.options.embedded_images === false ? 'skipped' : 'ocr', confidence: 0.98, detail: '1417×992px, 가로세로 1.43' },
    ],
    tools: ['pdfplumber 0.11.10', ocrTool],
    warnings: [],
    read_ms: held ? 310 : 3120,
  }
  if (held) return { ...base, ok: true, latency_ms: 320, summary: '텍스트만 설정이라 2쪽은 OCR하지 않고 보류합니다. 적용하면 이런 서류는 처리 보류됩니다.', output }
  Object.assign(output, {
    cer: document ? undefined : 0,
    preview: [
      '[파일명]',
      '[지원자]_지원서류_합본.pdf',
      '',
      '[작성자]',
      '[지원자]',
      '',
      '[1쪽]',
      '지원서류 합본 (1/2)',
      '지원자: [지원자] 지원 직무: 공장 자동화',
      '연락처: [전화-1] / [이메일-1]',
      '',
      '[1쪽 그림 2 (OCR)]',
      '국가기술자격증',
      '자격종목: 정보처리기사',
      '성명: [지원자]',
      '생년월일: [생년월일-1]',
      '',
      '[2쪽 (OCR)]',
      '이력서',
      '성명: [지원자] ([지원자])',
      '학력: [학교-1] 메카트로닉스공학 졸업',
    ].join('\n'),
    preview_truncated: false,
    replacements: 20,
  })
  return { ...base, ok: true, latency_ms: 3400, summary: 'PDF 2쪽을 읽었습니다 (OCR 1쪽, 그림 1개).', output }
}

export function testResult(role: string, spec: ModelSpec, audio: File | null, document: File | null = null): ModelTestResult {
  const model = modelName(spec, role)
  if (role.startsWith('document.')) return readingTest(role, spec, document, model)
  const base = { ok: true, model, error: null, audio: null as ModelTestResult['audio'] }
  if (role.startsWith('llm.')) {
    const output: Record<string, unknown> = {
      structured: { echo: '모델 연결 확인 문장입니다', sum: 42 },
      input_tokens: 61,
      output_tokens: 18,
      server_model: model,
      generate_ms: 840,
      first_token_ms: 310,
      stream_ms: 620,
      stream_text: '모델 연결 확인 문장입니다',
    }
    if (spec.impl === 'open_model_server') output.server_models = [model]
    return { ...base, latency_ms: 1460, summary: '구조화 출력(JSON)과 스트리밍으로 지시대로 답했습니다. 응답 0.8초, 스트리밍 첫 토큰 0.3초.', output }
  }
  if (role === 'embedding') {
    const dims = spec.impl === 'bge_m3' ? 1024 : Number(spec.options.dimensions ?? 768)
    const sparse = spec.impl !== 'vertex_embedding'
    const [similar, unrelated] = spec.impl === 'fake' ? [0.42, 0.0] : [0.633, 0.375]
    return {
      ...base,
      latency_ms: spec.impl === 'bge_m3' ? 2600 : 120,
      summary: `${dims}차원 벡터 3개${sparse ? ', 단어 일치 가중치 포함' : ''}. 비슷한 문장 ${similar.toFixed(2)}, 무관한 문장 ${unrelated.toFixed(2)}.`,
      output: { vectors: 3, dimensions: dims, expected_dimensions: dims, sparse, similar, unrelated, ...(sparse ? { lexical: 0.0497 } : {}) },
    }
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
