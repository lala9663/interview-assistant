# interview-assistant

JD 기반 서류 선별, 실시간 면접 보조(STT + 꼬리질문), 평점, 면접관 기록, 스케줄 매칭을 하나로 묶는 AI 면접 어시스턴트.

- 업무정의서: https://claude.ai/artifact/KHpkqy2oKKChicmheA2byK
- PoC 환경: Google Cloud (Vertex AI, Speech-to-Text v2, Cloud SQL)
- 원칙: LLM / STT / 임베딩 / 화자분리는 전부 `config/providers.yaml`에서 교체한다. 업무 로직은 `providers/base.py`의 인터페이스만 호출한다.

## 구조

```
config/
  providers.yaml        # PoC 기본값 (GCP)
  providers.fake.yaml   # 자격증명 없이 로컬 실행·테스트용
  deid.yaml             # 비식별화: 토큰 형식, 사전 경로, 탐지기 목록, 예외 목록
  deid/                 # 학교·회사 사전 초안 (공개 기관명)
src/interview_assistant/
  config.py             # 설정 로더 (env + providers.yaml)
  crypto.py             # 컬럼 암호화 (Fernet, IA_ENCRYPTION_KEY)
  db.py                 # 엔진, 세션 팩토리
  main.py               # FastAPI 앱 (/health, /api 라우터, 시작 시 멈춘 AI 채점 재개)
  runtime.py            # 앱이 들고 있는 것: provider, DB, 비식별화, AI 게이트웨이, 전사 허브, 백그라운드 작업
  models/               # ORM 모델 17개 (업무정의서 6장 13개 + 비식별 역매핑 + 사전 질문·꼬리질문 후보·전사 구간)
  domain.py             # JSON 컬럼 모양 (역량, 지원자 프로필)
  interviews.py         # 단계(stage)·집계·세션이 쓰는 역량 사전 규칙
  schedule.py           # 공통 빈 시간, 슬롯 후보 (프론트 lib/schedule.ts와 같은 규칙 + 잡힌 면접 제외)
  api/                  # REST·SSE API (docs/api-contract.md). routes/ 기능별 라우터, schemas.py 응답 스키마, views.py ORM → 응답
  ai/                   # AI 작업: gateway(가드 → provider → 감사 로그), guard, prompts, competency, screening, followups, scoring
  live/                 # 실시간 전사: hub(STT → 비식별화 → SSE), audio(오디오 소스, 지금은 대본 읽는 가상 지원자)
  demo/                 # 데모 데이터(프론트 모의 데이터와 같은 가상 데이터)와 시드, 가상 지원자 대본
  deid/                 # 비식별화 (업무정의서 9장)
    deidentifier.py     # 원문 -> 토큰 치환 텍스트. LLM으로 가는 유일한 통로
    service.py          # 앱용: 설정·사전·탐지기를 한 번 만들고 DB 세션마다 Deidentifier를 준다
    detectors/          # 교체 가능한 탐지기: 본인 정보, 정규식, 사전, 형태 패턴, 호칭 붙은 이름, NER 자리
    store.py            # 토큰 발급과 역매핑 저장 (원래 값은 암호화)
    reidentify.py       # 재식별. 역매핑을 복호화하는 유일한 곳, 호출마다 감사 로그
    documents.py        # 추출 문서 전체(파일명·속성 포함)를 블록 단위로 비식별화. 스캔본은 거부
    leaks.py            # 누출 검수 로직 (텍스트 샘플, 파일 샘플)
    review.py           # 사람이 보는 검토 리포트 (HTML 1개)
  documents/            # 서류 텍스트 추출 (5단계에서 앞당김). 원본 영역 전용
    base.py             # DocumentExtractor 인터페이스, 형식 판별, extract_document
    pdf.py, word.py, powerpoint.py, webpage.py   # PDF, DOCX, PPTX, HTML 구현
    normalize.py        # NFC, 제로폭 문자 제거, 전각 숫자 변환 (모든 추출 결과에 적용)
  providers/
    base.py             # LLMProvider, STTProvider, EmbeddingProvider, DiarizationProvider
    registry.py         # impl 이름 -> 구현 클래스
    fake.py             # 자격증명 없이 도는 구현 (speed로 지연 흉내)
    fake_tasks.py       # fake LLM이 앱 프롬프트에 규칙으로 답하는 부분 (모양만 그럴듯, 품질 아님)
scripts/
  seed_demo.py          # 데모 데이터 시드 (공고 3, 지원자 20, 면접관 5, 진행 중 1, 완료 4)
  export_mock_data.mjs  # 프론트 모의 데이터 → src/interview_assistant/demo/mock_data.json
  check_leaks.py        # 비식별화 누출 검수 (텍스트 샘플 / --documents 파일 샘플 / --report 검토 리포트)
  make_resume_fixtures.py  # 가상 이력서 20건과 정답 목록 생성
tests/
  fixtures/deid_samples.yaml  # 합성 텍스트 샘플 20건과 정답 목록
  fixtures/resumes/     # 가상 이력서 파일 20건 (PDF 6, DOCX 4, PPTX 3, HTML 4, 스캔 PDF 3)과 manifest.yaml
docs/
  api-contract.md       # 프론트 ↔ 백엔드 REST·SSE 계약, 모델 결정, 남은 과제 (백엔드 구현 완료, fake provider)
frontend/               # 면접관 UI (Vue 3). 백엔드 없이 모의 API(MSW)로 전 화면 동작
  src/api/              # types.ts(모델과 1:1), endpoints, TanStack Query composable, SSE 파서
  src/mocks/            # 모의 API: 가상 데이터, 핸들러, 실시간 전사·꼬리질문 스트림 흉내
  src/features/         # 화면: dashboard, postings, screening, sessions, interview(실시간), evaluation, schedule
```

## 실행

```bash
uv sync
cp .env.example .env
```

`.env`에서 두 가지를 정한다.

- `IA_ENCRYPTION_KEY`: 지원자 신원과 비식별 역매핑을 암호화하는 키. 없으면 업로드·답변·메모처럼 비식별화가 필요한 쓰기가 503으로 거부된다. 만들기: `uv run python -c "from interview_assistant.crypto import FieldCipher as F; print(F.generate_key())"`. 잃어버리면 저장된 신원을 되돌릴 수 없고, 커밋하지 않는다.
- `IA_PROVIDERS_FILE`: GCP 자격증명이 없으면 `config/providers.fake.yaml`. 모든 AI 기능이 fake provider로 돈다 (아래 "AI" 참조).

DB를 만들고 데모 데이터를 넣은 뒤 서버를 띄운다.

```bash
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset
uv run uvicorn interview_assistant.main:app --reload
```

- 시드는 프론트 모의 데이터와 같은 가상 데이터를 지금 시각 기준으로 깐다 (진행 중 면접 1, 오늘 일정, 완료 4 중 1건은 AI 채점 중). 다른 날 다시 쓰려면 `--reset`으로 다시 넣는다. 지원자 신원도 지어낸 값(010-0000-xxxx, example.com)을 실제처럼 암호화해 넣는다.
- 로그인은 아직 없다. `IA_DEV_INTERVIEWER`(사번, 시드의 김서연 = E24017)가 로그인한 면접관이다.
- 서버는 한 프로세스로 띄운다 (실시간 전사 상태가 메모리에 있다). `--workers`를 쓰지 않는다.
- API 문서: http://localhost:8000/docs, 계약: [docs/api-contract.md](docs/api-contract.md).

```bash
uv run pytest
```

테스트는 외부 네트워크 없이 돈다 (API 테스트는 fake provider와 임시 SQLite 사본을 쓴다).

## AI (fake provider로 연결)

서류 선별, 역량 사전 초안, 꼬리질문, 평점은 모두 `ai/gateway.py`를 거쳐 `config/providers.*.yaml`에 적힌 provider를 부른다. 호출 전에 프롬프트를 비식별 필드로만 만들고 가드가 식별 정보를 다시 확인하며, 호출마다 감사 로그를 남긴다. `providers.yaml`의 `impl`만 실제 구현(`anthropic_vertex` 등, 3단계)으로 바꾸면 실제 모델로 바뀐다. `tests/test_api_privacy.py`가 YAML에만 적힌 provider로 모든 호출이 가는지, 프롬프트에 식별 정보가 없는지 검사한다.

- fake LLM은 앱의 프롬프트 태그를 읽어 규칙으로 답한다 (`providers/fake_tasks.py`). 화면과 흐름을 확인하는 용도이고, 내용의 품질은 실제 모델 연결 뒤에 검증한다.
- 실시간 전사는 실제 오디오(11단계, LiveKit) 전까지 `live/audio.py`의 가상 지원자가 데모 대본을 읽고 fake STT가 받아 적는다. 속도는 `speed`(providers.fake.yaml)와 `IA_DEMO_SPEED`, 1이면 프론트 모의 모드와 비슷하다.
- 업로드한 원본 서류는 `IA_UPLOADS_DIR`(기본 `uploads/`, git 제외)에 지원서 id 이름으로 저장하고 응답에는 내보내지 않는다.

## DB

모델은 `src/interview_assistant/models/`, 마이그레이션은 `migrations/versions/`. 연결 문자열은 `IA_DATABASE_URL` (기본 SQLite). 컬럼 타입은 SQLite, PostgreSQL, MySQL 공통 범위만 쓴다.

```bash
uv run alembic upgrade head
```

모델을 바꾼 뒤 마이그레이션 생성:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

`tests/test_migrations.py`가 마이그레이션 결과와 모델이 일치하는지 검사한다.

## 비식별화

LLM에는 `Deidentifier`를 거친 텍스트만 보낸다. 같은 지원자 안에서 같은 값은 세션·문서를 가로질러 항상 같은 토큰(`[지원자]`, `[학교-1]`, `[회사-2]` …)이 된다. 원래 값은 `deid_mappings`에 암호화해 두며, 되돌리는 것은 `deid/reidentify.py`만 한다.

```python
config = load_deid_config(Settings().deid_file)
store = SqlTokenStore(session, FieldCipher.from_settings(), config.token_formats())
result = build_deidentifier(config, store).deidentify(text, candidate_id=cid, known=identity)
```

- 토큰 형식, 사전 파일, 켤 탐지기, 치환 예외는 `config/deid.yaml`에서 바꾼다. 토큰 형식은 아직 초안이다.
- 학교·회사 사전은 `config/deid/*.txt` (한 줄에 `정식명 | 별칭 | ...`). 사내 목록은 파일을 추가하고 `deid.yaml`에 나열한다.
- 한국어 NER은 `deid/detectors/ner.py`의 `EntityRecognizer`를 구현해 붙인다. 지금은 모델 없이 규칙 기반이다.
- 글자 사이에 공백이 들어간 값(자간, "0 1 0 - 1 2 3 4 - 5 6 7 8", "john @ example . com", "누 리 대 학 교")도 지원서에 없는 값까지 규칙으로 잡는다. 전화·이메일·주민번호 정규식과 학교·회사 형태 패턴은 원문과 함께 공백을 뺀 사본(`deid/text.py`의 `without_letter_spacing`, 사본→원문 위치 대응표)에도 돌리고, 찾은 구간을 원문 위치로 되돌려 띄어 쓴 원문 전체를 치환한다. 사본에서 빼는 공백은 한 글자끼리 사이(그중 가장 좁은 간격)와 @ . - _ 앞뒤뿐이라 "있는 대학교" 같은 일반 단어는 붙지 않고, 전화는 010·지역번호 접두와 자릿수, 이메일은 @와 도메인, 주민번호는 유효한 날짜가 그대로 필요하다. 이름처럼 단어 경계가 필요한 탐지는 원문에서만 하며, 지원서 이름은 글자 사이 공백 여러 칸("권  하  린")까지 허용한다. 남은 한계: 지원서에 없는 띄어 쓴 제3자 이름·영문 이름·생년월일·주소, 사전에만 있고 형태로는 안 보이는 기관명("카 카 오")은 못 잡는다. 글자마다 띄어 쓴 문장은 학교·회사 이름으로 과잉 치환될 수 있다.
- 누출 검수 (합성 샘플 20건, 네트워크 없이 실행):

```bash
uv run python scripts/check_leaks.py
```

실제 샘플로 검수할 때는 같은 형식의 YAML을 만들어 `--samples`로 넘긴다. 리포트는 값을 가려서 출력한다 (`--show-values`로 해제). 정답 목록에 없어도 전화·이메일·주민번호 형태가 남으면 실패이며, 이 검사는 공백을 전부 뺀 사본도 보므로 띄어 쓴 값이 남아도 드러난다.

### 서류 파일

LLM으로 가는 서류 텍스트는 `extract_document` → `deidentify_document`만 거친다. 이미지는 세기만 하고 버리며, 원본 파일이나 이미지를 모델로 보내는 경로는 없다.

```python
document = extract_document(upload_bytes, upload_filename)   # PDF, DOCX, PPTX, HTML
result = deidentify_document(deid, document, candidate_id=cid, known=identity)
prompt_text = result.text   # 파일명·문서 속성·본문·표·머리글·바닥글·노트·링크·숨은 텍스트, 토큰 치환본
```

- 추출 결과는 블록 단위(`documents/types.py`의 `BlockKind`)다. 흰 글씨, 0.5pt 글자, 슬라이드 밖 도형, `display:none`처럼 보이지 않는 텍스트는 `hidden` 블록으로 따로 둔다.
- PDF의 자간 넓힌 줄은 글자 좌표로 되돌린다(`documents/pdf.py`의 `close_letter_spacing`). 공백 글자 없이 고른 간격으로 이어진 세 글자 이상(같은 줄이면 두 글자 단어도)은 붙이고, 공백 글자나 더 넓은 간격은 단어 사이로 남긴다: "권 하 린 · 이 력 서" → "권하린 · 이력서". 보통 텍스트와 실제 공백으로 띄운 글자("이 력 서" 제목)는 바뀌지 않는다.
- 텍스트 레이어가 없는 쪽(스캔본)이 하나라도 있으면 `needs_ocr`이고, `deidentify_document`가 `OcrRequired`로 거부한다. OCR은 아직 없으므로 문서 전체를 보류한다.
- HWP/HWPX와 구형 .doc/.ppt는 `UnsupportedFormat`으로 거부한다.
- 추출기 교체: `extract_document(..., extractors={"pdf": MyPdfExtractor()})`. 구현은 `DocumentExtractor`를 따른다.
- 라이브러리: pdfplumber(MIT, pdfminer.six MIT, pypdfium2 Apache-2.0/BSD-3), python-docx·python-pptx(MIT), beautifulsoup4(MIT), lxml(BSD). PyMuPDF(AGPL)는 쓰지 않는다.

파일 단위 누출 검수 (가상 이력서 20건: 추출 → 비식별화 → 정답 값 검사, 파일명·속성 포함, 네트워크 없음):

```bash
uv run python scripts/check_leaks.py --documents
```

사람이 보는 검토 리포트 (샘플별 원본 추출 텍스트와 비식별본 나란히, 토큰 강조, 속성·버린 이미지 수, OK/누출 체크):

```bash
uv run python scripts/check_leaks.py --documents --report
```

리포트는 `reports/deid-review.html`에 생기고 브라우저로 연다. 원문이 그대로 들어 있으므로 원본 영역 문서로 다룬다: `reports/`는 git에서 제외되어 있고, 공유·첨부하지 않는다. 체크 결과는 그 브라우저에만 저장되며 "결과 복사"(TSV)나 "결과 저장"(JSON)으로 꺼낸다. 실제 서류로 검수할 때는 같은 형식의 manifest를 만들어 `--documents path/to/manifest.yaml`로 넘긴다.

가상 이력서 다시 만들기 (dev 의존성 reportlab, pillow 필요). 한글 PDF와 스캔 이미지에 쓸 TrueType 폰트는 시스템에서 읽고 커밋하지 않는다. 기본으로 맑은 고딕·나눔고딕 경로를 찾고, 다른 폰트는 `--font` 또는 `IA_FIXTURE_FONT`로 준다:

```bash
uv run python scripts/make_resume_fixtures.py --font C:/Windows/Fonts/malgun.ttf
```

같은 폰트면 결과 파일이 바이트 단위로 같고, `manifest.yaml`(정답 목록)은 파일을 그리면서 기록한 값으로 쓴다.

## 프론트엔드 (면접관 UI)

`frontend/`. Vite + Vue 3 + TypeScript(strict, `vue-tsc`), Tailwind CSS v4 + shadcn-vue 방식 컴포넌트(Reka UI), TanStack Query(`@tanstack/vue-query`), Vue Router, MSW, Chart.js(`vue-chartjs`), vue-sonner, lucide 아이콘(`@lucide/vue`). 명령 팔레트는 Reka UI Listbox, 화면 전환 효과는 Vue `<Transition>`과 CSS만 쓴다. 테스트는 Vitest + Testing Library(Vue) + MSW(node), 린트는 eslint-plugin-vue + typescript-eslint. 폰트는 Pretendard(OFL)를 npm 패키지에서 자체 호스팅한다. Node 24 이상. 이전 React 버전은 git 이력(`93a1780`)에 있다.

화면: 대시보드, 공고·역량 사전(FR-02), 서류 선별(FR-01·03), 면접 목록, 실시간 면접(FR-04~08), 평가 결과(FR-07·08), 면접관 스케줄(FR-09). 다크 모드 기본(시스템 설정 따름), Ctrl/⌘+K 명령 팔레트.

```bash
cd frontend
npm ci
npm run dev          # 모의 API 모드 (백엔드 불필요) → http://localhost:5173
```

모의 모드(`VITE_USE_MOCKS=true`, `.env.development`)에서는 브라우저의 MSW가 `/api` 요청에 답한다. 가상 데이터(공고 3, 지원자 20, 면접관 5, 진행 중 면접 1, 완료 면접 4)는 새로고침하면 처음 상태로 돌아간다. 진행 중 면접 화면을 열면 지원자 답변이 글자 단위로 스트리밍되고, 답변이 끝나면 꼬리질문 후보가 스트리밍된다. 모의 모드에서 `/api`가 모두 502로 실패하면 브라우저가 MSW 서비스 워커를 재시작해 등록이 풀린 것이다. 새로고침하면 된다.

백엔드 연결 모드는 같은 `/api` 경로를 Vite 프록시로 FastAPI(`localhost:8000`)에 보낸다. 대상은 `frontend/.env.api`의 `VITE_API_PROXY_TARGET`. 데이터는 DB에서 오고 새로고침해도 남는다. 위 "실행"대로 마이그레이션·시드를 한 뒤:

```bash
uv run uvicorn interview_assistant.main:app --reload   # 저장소 루트에서
cd frontend && npm run dev:api                         # → http://localhost:5173
```

서류 선별 화면의 "서류 업로드"로 PDF·DOCX·PPTX·HTML을 올리면 텍스트 추출 → 비식별화 → 프로필·선별(fake LLM) → 표에 새 가명(CAND-0021 …)으로 들어온다. 이름·연락처는 비식별화에만 쓰인다. 스캔본은 OCR이 없어 거부한다. 테스트용 가상 이력서는 `tests/fixtures/resumes/`에 있다.

검사와 빌드:

```bash
npm run check        # 타입 검사 + 린트 + 테스트(Vitest) + 빌드
npm run build        # dist/ (실제 API용, VITE_USE_MOCKS=false)
npm run build:mock   # 백엔드 없이 띄우는 데모 빌드
```

의존성 버전은 `package.json`에 정확히 고정하고 `package-lock.json`을 커밋한다 (공개 후 2주 이상 지난 버전). 의존성을 바꿀 때는 `npm install --before=<2주 전 날짜>`로 설치해 전이 의존성까지 같은 기준을 지킨다. 번들에 들어가는 라이브러리는 MIT·ISC·Apache-2.0·BSD 계열이고 폰트는 OFL-1.1이다. 빌드·테스트에만 쓰고 번들에 들어가지 않는 예외: lightningcss(MPL-2.0, Tailwind v4와 Vite의 CSS 처리), jsdom이 쓰는 mdn-data(CC0-1.0)와 @csstools/*(MIT-0), glob·minimatch·lru-cache 등(BlueOak-1.0.0).

## 진행 순서

[docs/implementation-order.md](docs/implementation-order.md) 참조. 현재 2단계(비식별화) 구현 완료, 사용자 확인(토큰 형식, 사전, 검토 리포트로 20건 수동 검수) 대기. 4~8단계의 API·저장 부분과 9단계 화면 연결은 fake provider로 먼저 구현했다(2026-10-23): [API 계약](docs/api-contract.md)의 모든 경로, 업로드, 실시간 전사·꼬리질문 SSE, AI 채점, 시드. 남은 것은 3단계 실제 LLM Provider 연결과 프롬프트별 품질 검증, 10~11단계 오디오, 로그인(계약 문서 5장).
