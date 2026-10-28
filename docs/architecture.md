# 구조

## 저장소

```
config/
  providers.yaml        # PoC 기본값 (GCP). 처음 기동할 때만 읽고, 그 뒤로는 DB의 모델 설정이 이긴다
  providers.fake.yaml   # 자격증명 없이 로컬 실행·테스트용
  deid.yaml             # 비식별화: 토큰 형식, 사전 경로, 탐지기 목록, 예외 목록
  deid/                 # 학교·회사 사전 초안 (공개 기관명)
src/interview_assistant/
  config.py             # 설정 로더 (env + providers.yaml)
  crypto.py             # 컬럼 암호화 (Fernet, IA_ENCRYPTION_KEY)
  db.py                 # 엔진, 세션 팩토리
  main.py               # FastAPI 앱 (/health, /api 라우터, 시작 시 멈춘 AI 채점과 남은 수신 이벤트 재개)
  runtime.py            # 앱이 들고 있는 것: 모델 관리자(역할별 provider), DB, 비식별화, 전사 허브, 지원서 수신 큐, 검색(질문 은행 색인), 백그라운드 작업
  intake/               # 지원서 수신: 통로와 분리된 처리 함수(service), 사이트 입력 칸(forms), 사이트 이벤트 명세(site), HMAC 서명(signature), 받기·반영(events), 백그라운드 큐(worker)
  ai_models/            # 관리자 > 모델 설정: store(활성 설정·이력 DB), manager(revision별 스냅샷, 세션 고정, 원자적 교체), probe(연결 테스트)
  models/               # ORM 모델 (업무정의서 6장 13개 + 비식별 역매핑 + 사전 질문·꼬리질문 후보·전사 구간 + 모델 설정·이력 + 전형 차수·차수 결정·확인할 점 + 질문 은행·평점 기준 예시·임베딩 벡터·색인)
  retrieval/            # 검색: vectors(저장 형식·유사도), index(VectorIndex 인터페이스와 메모리 구현), documents(무엇을 임베딩하나), service(색인 동기화·재색인·질의), bank(질문 은행 후보, 같은 질문 판정, 채점 기준점 고르기, 지원자 답변 복사 거절)
  domain.py             # JSON 컬럼 모양 (역량, 지원자 프로필)
  interviews.py         # 전형 진행 규칙: 서류 → 각 차수 → 최종 단계(progress·stage), 다음 차수 대상, 같은 차수 중복 거부 사유, 차수별 집계, 이전 차수 Q&A
  schedule.py           # 공통 빈 시간, 슬롯 후보 (프론트 lib/schedule.ts와 같은 규칙 + 잡힌 면접 제외)
  agent/                # MCP 서버 (agent-integration.md): settings(IA_MCP_*), api(질문한 사람의 토큰으로 REST 호출), tools(읽기 13·제안 3), shape(KST·라벨·링크·연락처 모양 가림), server(stdio·streamable HTTP)
  api/                  # REST·SSE API (api-contract.md). agent_access = 에이전트 토큰·읽기 전용 가드·호출 감사, routes/ 기능별 라우터(admin = 모델 설정, intake = 채용 사이트 수신·연동 현황, 관리자만), schemas.py 응답 스키마, views.py ORM → 응답
  ai/                   # AI 작업: gateway(가드 → provider → 감사 로그), guard, prompts, competency(차수별 초안, 비슷한 공고의 확정 사전 참고), screening, followups(질문 은행 후보 먼저 + AI 스트리밍, 같은 질문 거르기, 이전 차수 Q&A 참고), scoring(평점 기준점), checkpoints(다음 차수 확인할 점), presets(차수 사전 질문 초안·이어 질문), question_rules(금지 질문 규칙)
  live/                 # 실시간 전사: hub(STT → 비식별화 → SSE, 답변 조각 이어 붙이기, 질문 중/답변 듣는 중), audio(오디오 소스, 대본 읽는 가상 지원자), microphone(마이크: VAD로 말소리만, 답변 끝 판정), recording(원본 영역 WAV), prefetch(답변 중 미리 임베딩), retranscribe(면접 뒤 녹음 재전사), codes(오류 코드)
  demo/                 # 데모 데이터(프론트 모의 데이터와 같은 가상 데이터)와 시드, 가상 지원자 대본
  deid/                 # 비식별화 (업무정의서 9장, deidentification.md)
  documents/            # 서류 읽기, 원본 영역 전용 (document-reading.md): reading(쪽별 텍스트·OCR 선택, DocumentReader), quality(깨짐 판정), images(증명사진 판정), ocrfix(비슷한 글자), render(PDF 쪽 그림), 형식별 추출기 pdf·word·powerpoint·webpage·hwp·hwpx·image, legacy(LibreOffice 변환)
  providers/
    base.py             # LLMProvider, STTProvider, EmbeddingProvider, DiarizationProvider, OCRProvider (공통: model, warm_up), 오디오 형식
    registry.py         # impl 이름 -> 구현 클래스
    catalog.py          # 관리자 화면이 고르는 목록: 역할, 데이터 위치, 옵션 스키마, 요구 조건(네트워크 없이)
    weights.py          # 모델 가중치(Whisper, PaddleOCR, Tesseract 한국어 데이터): 커밋 고정·sha256, 이어받는 다운로드, 진행률
    programs.py         # 시스템 프로그램(Tesseract, LibreOffice) 찾기와 버전, 네트워크 없이
    audio.py            # 파일 URI, 16kHz PCM 디코딩(PyAV), 조각 내기, 내장 한국어 샘플(samples/, FLEURS CC BY 4.0)
    stt/faster_whisper.py  # 로컬 Whisper STT (CPU int8, 한국어, VAD, stream·transcribe)
    embedding/bge_m3.py # 로컬 BGE-M3 임베딩 (ONNX Runtime CPU, 밀집 1024 + 희소, 같은 가중치는 인스턴스끼리 공유)
    ocr/paddle.py, ocr/tesseract.py  # 로컬 OCR (PP-OCRv5 한국어 CPU, Tesseract kor+eng)
    isolated.py         # 네이티브 엔진을 작업 프로세스에서 돌리기 (PaddleOCR: 그 DLL이 faster-whisper와 충돌)
    samples/documents/  # 서류 읽기 연결 테스트용 가상 이력서
    fake.py             # 자격증명 없이 도는 구현 (speed로 지연 흉내)
    fake_tasks.py       # fake LLM이 앱 프롬프트에 규칙으로 답하는 부분 (모양만 그럴듯, 품질 아님)
migrations/versions/    # Alembic 0001~0007
scripts/
  seed_demo.py          # 데모 데이터 시드
  grant_admin.py        # 면접관에게 관리자 권한 (0004 이전 DB용, SSO 전까지)
  agent_token.py        # 에이전트(MCP) 개발용 토큰 발급 (SSO 전까지)
  try_mcp.py            # 실행 중인 MCP 서버의 도구를 SDK 클라이언트로 한 번씩 부르기
  bench_whisper.py      # Whisper 크기별 속도·메모리·CER·스트리밍 지연 측정
  bench_ocr.py          # OCR 엔진별 쪽당 시간·메모리·CER 측정
  bench_embedding.py    # BGE-M3 로딩·임베딩·1,000건 색인·검색 시간, 메모리(단독, Whisper·PaddleOCR과 함께)
  eval_retrieval.py     # 한국어 검색 품질: 가상 답변 → 맞는 질문 상위 3개 적중률 (하이브리드 vs 의미만)
  check_leaks.py        # 비식별화 누출 검수 (텍스트 샘플 / --documents 파일 샘플, --ocr로 OCR 포함 / --report 검토 리포트)
  fake_recruiting_site.py  # 가짜 채용 사이트: 서명된 지원서 이벤트 약 500건(중복·순서 바뀜·철회·일부러 넣은 오류), 처리 결과·시간 보고
  make_resume_fixtures.py  # 가상 이력서 31건과 정답 목록 생성 (hwp_writers.py: HWP 5.0·HWPX 쓰기)
  export_mock_data.mjs  # 프론트 모의 데이터 → src/interview_assistant/demo/mock_data.json
tests/
  fixtures/deid_samples.yaml  # 합성 텍스트 샘플 20건과 정답 목록
  fixtures/retrieval_eval.yaml  # 검색 평가 세트: 가상 답변 37개와 정답 질문
  fixtures/resumes/     # 가상 이력서 파일 31건 (PDF 텍스트 6·스캔 3·깨짐 1·혼합 1, DOCX 5, PPTX 4, HTML 4, HWPX 1, HWP 2, .doc 1, .ppt 1, JPG 1, PNG 1)과 manifest.yaml
docs/                   # 이 문서들
frontend/               # 면접관 UI (Vue 3, frontend.md)
weights/                # 내려받은 모델 가중치 (git 제외)
uploads/, recordings/, reports/   # 원본 영역 (git 제외)
```

## AI 호출 흐름

서류 선별, 역량 사전 초안, 꼬리질문, 평점은 모두 `ai/gateway.py`를 거친다.

1. 프롬프트는 비식별 필드로만 만든다(`ai/prompts.py`, 입력은 태그로 감싸고 태그 안 지시문은 따르지 않게 한다).
2. 가드(`ai/guard.py`)가 호출 직전에 지원자 텍스트에 그 지원자의 이름·연락처·학교·회사가 남았는지, 전화·이메일·주민번호 모양이 있는지 다시 보고, 남았으면 호출하지 않는다.
3. 역할(`primary`, `screening`)에 정해진 provider를 부른다. 어떤 provider인지는 관리자 화면에서 정한다([ai-models.md](ai-models.md)).
4. 호출마다 감사 로그를 한 줄 남긴다(성공·실패·가드 거부, 모델, 프롬프트 버전, 토큰 수). 프롬프트와 응답 본문은 남기지 않는다.

`tests/test_api_privacy.py`가 YAML로 정한 provider와 관리자 화면에서 바꾼 provider 모두로 모든 호출이 가는지, 어떤 응답과 프롬프트에도 식별 정보가 없는지 검사한다.

- fake LLM은 앱의 프롬프트 태그를 읽어 규칙으로 답한다(`providers/fake_tasks.py`). 화면과 흐름을 확인하는 용도이고, 내용의 품질은 실제 모델 연결(3단계) 뒤에 검증한다.
- 면접 세션은 시작할 때의 모델 설정에 고정된다. 실시간 전사, 꼬리질문, 종료 뒤 AI 채점까지 그 provider로 끝내고, 결과에는 실제 쓴 모델 이름이 남는다.

## 검색 (질문 은행·임베딩)

회사가 쓴 텍스트(승인된 질문 은행 질문과 꼬리질문 예시, 평점 기준 예시, 확정 역량 사전)만 임베딩해 `embedding_vectors`에 둔다(float32 BLOB + 희소 가중치 JSON, 만든 모델의 `index_key`와 함께). 검색은 `retrieval/index.py`의 `VectorIndex` 뒤의 메모리 구현이고, DB 엔진을 정하면 pgvector 등으로 바꾼다. 자세한 규칙은 [question-bank.md](question-bank.md).

```
답변 닫힘 ─▶ 가드 ─▶ 답변 임베딩 ─▶ 질문 은행 검색 ─▶ 같은 질문 거르기 ─▶ 질문 은행 후보 0~2개 (바로)
                                   (직군·역량·차수,      (이 면접 + 이전 차수,        │
                                    하이브리드 점수)       의미 유사도)               ▼
                         가까운 질문 4개 ─▶ LLM 프롬프트 예시 ─▶ AI 후보 스트리밍 ─▶ 같은 질문이면 거둬들임
```

- 색인은 하나가 검색에 쓰인다(가장 최근 ready). 임베딩 모델을 바꾸면 백그라운드 작업이 새 모델로 모두 임베딩하고, 끝날 때까지 이전 색인과 그 색인을 만든 provider로 검색한다. 끝나면 참조 하나로 바꾸고 이전 벡터를 지운다. 재시작 뒤에도 `embedding_indexes.spec`으로 그 provider를 다시 만든다.
- 승인·폐기·수정은 그 자리에서 색인에 반영한다(바뀐 텍스트·필터 칸만 다시 임베딩). 검색 결과는 DB에서 승인 상태를 한 번 더 확인해, 방금 폐기한 질문이 제안되지 않는다.
- 질의는 세션에 고정된 provider가 아니라 지금 검색하는 색인의 모델로 임베딩한다(다른 모델의 벡터는 비교할 수 없다). 지원자 답변은 가드를 통과한 비식별 답변만, 저장하지 않고 임베딩한다.
- 채점은 검색을 쓰지 않는다. 기준점은 직군·역량으로 고르고, 지원자 답변과의 유사도는 계산하지 않는다.

## 에이전트 (MCP 서버)

사내 에이전트 플랫폼은 `agent/`의 MCP 서버를 거쳐 웹과 같은 REST API를 부른다. MCP 서버는 DB에 닿지 않고 기능 로직도 없어, 비식별화·권한·감사 로그는 API 한곳에서 돈다. 자세한 것은 [agent-integration.md](agent-integration.md).

```
에이전트 플랫폼 ─(MCP)─▶ agent/ ─(HTTP, 질문한 사람의 자격증명, X-Agent-*)─▶ /api ─ agent_guard(AgentIdentity → 면접관, 읽기만) ─ 라우트 ─ AgentAuditMiddleware(응답 전 agent.* 기록)
```

- 자격증명이 가리키는 면접관이 `Me`가 되고, 관리자 전용·"내 점수" 같은 규칙이 웹과 똑같이 돈다.
- 에이전트 토큰으로는 GET과 `agent_may_call` 표시가 붙은 POST(공통 빈 시간, 금지 질문 확인, 제안 기록)만 된다. 바꾸는 일은 제안으로 남기고 웹에서 사람이 반영한다.

## 면접 차수 (전형)

공고마다 차수 목록(`interview_rounds`: 순서, 이름, 기본 진행 방식, 권장 면접관 수, 이전 차수 점수 공개)이 있고, 역량 사전 버전과 사전 질문은 차수에 속한다. 세션은 한 차수에 속하고 시작할 때 그 차수의 확정본을 고정한다. 규칙은 `interviews.py` 한 곳에 있다.

```
서류 통과 ─▶ 1차 [대기 → 예정 → 진행 → 평가 대기 → 결정 대기 → 합격 / 보류 / 불합격]
                 합격 ─▶ 2차 [ … ] ─▶ … ─▶ 마지막 차수 합격 = 최종 합격 후보 (공식 결과는 채용 사이트)
```

- 차수 상태는 그 차수의 취소 아닌 최근 세션과 현재 결정(`round_decisions`의 가장 큰 revision)에서 나온다. 결정은 사람이 면접관 전원 제출 뒤에 하고, 바꾸면 새 revision이 쌓인다(감사 로그 `round.decided`·`round.decision_changed`). 다음 차수 세션이 생기면 이전 차수 결정은 바꿀 수 없다.
- 같은 차수 세션이 한 지원서에 동시에 둘 열리지 않게 API가 막고, DB도 `interview_sessions.active_round_id`(예정·진행 중일 때만 차수 id) + UNIQUE(application_id, active_round_id)로 막는다. flush 훅이 상태에 맞춰 칸을 채운다.
- N차 세션 화면은 이전 차수 요약을 받는다: 확인이 필요한 점(면접관이 남긴 것, AI가 채점 뒤 답변 인용과 함께 뽑은 것)과 메모는 늘, 점수와 결정 사유는 그 차수의 `show_previous_scores`가 켜졌을 때만 서버가 보낸다(기본 꺼짐, 기준점 효과를 피하려고).
- 꼬리질문 프롬프트는 이전 차수 Q&A(저장된 비식별 텍스트, 최근 8개)를 `<earlier_rounds>`로 받고 이미 물은 것을 반복하지 않는다. 이어 질문(`preset_questions.session_id`)은 이전 차수 답변과 확인할 점으로 이 지원자에게만 묻는 질문을 만들고, 기댄 답변을 그대로 인용한다. 이전 차수 텍스트도 모두 가드에 지원자 텍스트로 넘긴다.

## 실시간 전사

`live/hub.py`: 지원자 오디오 → 세션이 고정한 스트리밍 STT → 비식별화 → SSE(부분·확정 전사, 답변 닫힘). 확정 구간만 저장하고 원문은 원본 영역(`QAItem.answer_text`)에만 둔다.

- 마이크: 브라우저가 16kHz PCM16을 WebSocket(막히면 HTTP 청크)으로 보내면 `live/microphone.py`가 녹음(동의 시) → 잡음 억제(끔) → Silero VAD → 말소리만 STT로 넣고, 답변 끝 판정(침묵·Smart Turn)이 답의 조각을 끝낸다. 이어 말하면 같은 답에 붙는다. 자세한 것은 [audio-input.md](audio-input.md).
- 마이크를 붙이기 전에는 `live/audio.py`의 가상 지원자가 데모 대본을 텍스트로 보내고 fake STT가 받아 적는다. 속도는 `speed`(providers.fake.yaml)와 `IA_DEMO_SPEED`.
- 오디오 소스는 내보내는 형식을 밝힌다. 실제 음성은 16kHz 모노 16비트 PCM이고, STT provider가 그 형식을 못 읽으면(예: Whisper에 가상 지원자 텍스트) 그 면접은 수기 답변 입력으로 바뀐다.
- 상태는 프로세스 메모리에 있다. 서버를 여러 대 띄우려면 공유 버스가 필요하다.

## 지원서 수신 (통로와 처리)

지원서는 두 통로로 들어온다: 서류 선별 화면의 업로드(파일 1건 + 양식 신원)와 채용 사이트 연동(서명된 이벤트). 통로는 받은 것을 `intake/service.py`의 `ApplicationInput`으로 바꾸기만 하고, 처리는 `process_application` 하나가 한다.

```
업로드 화면 ─┐                                      ┌─ 공고 찾기 (id / 사이트 공고 번호)
채용 사이트 ─┼─▶ ApplicationInput ─▶ process_application ─┼─ 첨부 읽기 (documents/, 텍스트·OCR)
(압축 파일)  ┘      (통로가 만든다)        (하나뿐)     ├─ 지원자 찾기(지원자 번호 해시) 또는 만들기
                                                     ├─ 비식별화 (입력 칸·자기소개·첨부 전부)
                                                     ├─ 프로필 (입력 칸 그대로 / 없으면 모델)
                                                     └─ AI 선별 → 지원서 만들기·갱신 (보류로 시작)
```

- 채용 사이트 이벤트는 받자마자 202로 답하고 `intake_events`(큐이자 멱등성 기록)에 넣는다. 워커 `IA_INTAKE_WORKERS`개가 지원서 번호 단위로 차례를 지켜 반영하고(revision이 높은 것만), 서버가 재시작되면 남은 이벤트를 다시 처리한다. 형식·서명·재시도·오류 코드는 [site-intake-spec.md](site-intake-spec.md), API는 [api-contract.md](api-contract.md) "채용 사이트 연동".
- 처리 중 모델을 기다리는 동안 쓰기 트랜잭션을 열어 두지 않는다. 비식별화(토큰 쓰기)는 스레드에서 하고 그 스레드 안에서 커밋하며, 모델 호출마다 감사 로그를 바로 커밋한다. SQLite는 쓰기가 하나뿐이라, 이벤트 루프 위에서 잠금을 쥔 채 기다리면 다른 쓰기가 루프 전체를 멈춘다.
- 압축 파일 일괄 가져오기(남은 과제)는 같은 `process_application`에 통로 하나를 더하는 일이다.

## 업로드

업로드한 원본 서류는 `IA_UPLOADS_DIR`(기본 `uploads/`)에 지원서 id 이름으로 저장하고 응답에는 내보내지 않는다. 읽기(쪽마다 텍스트 층 또는 OCR, [document-reading.md](document-reading.md)) → 비식별화 → 프로필·선별 순서는 [api-contract.md](api-contract.md) "업로드"와 [deidentification.md](deidentification.md) "서류 파일". 처리는 시작할 때의 모델 설정 스냅샷 하나에서 AI와 읽기 도구를 함께 꺼내, 도중에 관리자가 설정을 바꿔도 그 지원서는 처음 설정으로 끝난다. 그림은 OCR로 텍스트만 꺼내고 버린다. 그림을 모델로 보내는 경로는 없다.
