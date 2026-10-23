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
  main.py               # FastAPI 앱
  models/               # ORM 모델 14개 (업무정의서 6장 13개 + 비식별 역매핑)
  deid/                 # 비식별화 (업무정의서 9장)
    deidentifier.py     # 원문 -> 토큰 치환 텍스트. LLM으로 가는 유일한 통로
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
    fake.py             # 테스트용 구현
scripts/
  check_leaks.py        # 비식별화 누출 검수 (텍스트 샘플 / --documents 파일 샘플 / --report 검토 리포트)
  make_resume_fixtures.py  # 가상 이력서 20건과 정답 목록 생성
tests/
  fixtures/deid_samples.yaml  # 합성 텍스트 샘플 20건과 정답 목록
  fixtures/resumes/     # 가상 이력서 파일 20건 (PDF 6, DOCX 4, PPTX 3, HTML 4, 스캔 PDF 3)과 manifest.yaml
```

## 실행

```bash
uv sync
cp .env.example .env
uv run uvicorn interview_assistant.main:app --reload
```

자격증명 없이 띄우려면 `.env`에서 `IA_PROVIDERS_FILE=config/providers.fake.yaml`.

```bash
uv run pytest
```

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

## 진행 순서

[docs/implementation-order.md](docs/implementation-order.md) 참조. 현재 2단계(비식별화) 구현 완료, 사용자 확인(토큰 형식, 사전, 검토 리포트로 20건 수동 검수) 대기. 5단계 서류 파싱 중 텍스트 추출은 2단계 검수용으로 앞당겨 구현했다. 다음은 3단계 실제 LLM Provider.
