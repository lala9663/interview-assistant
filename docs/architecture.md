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
  runtime.py            # 앱이 들고 있는 것: 모델 관리자(역할별 provider), DB, 비식별화, 전사 허브, 지원서 수신 큐, 백그라운드 작업
  intake/               # 지원서 수신: 통로와 분리된 처리 함수(service), 사이트 입력 칸(forms), 사이트 이벤트 명세(site), HMAC 서명(signature), 받기·반영(events), 백그라운드 큐(worker)
  ai_models/            # 관리자 > 모델 설정: store(활성 설정·이력 DB), manager(revision별 스냅샷, 세션 고정, 원자적 교체), probe(연결 테스트)
  models/               # ORM 모델 (업무정의서 6장 13개 + 비식별 역매핑 + 사전 질문·꼬리질문 후보·전사 구간 + 모델 설정·이력)
  domain.py             # JSON 컬럼 모양 (역량, 지원자 프로필)
  interviews.py         # 단계(stage)·집계·세션이 쓰는 역량 사전 규칙
  schedule.py           # 공통 빈 시간, 슬롯 후보 (프론트 lib/schedule.ts와 같은 규칙 + 잡힌 면접 제외)
  api/                  # REST·SSE API (api-contract.md). routes/ 기능별 라우터(admin = 모델 설정, intake = 채용 사이트 수신·연동 현황, 관리자만), schemas.py 응답 스키마, views.py ORM → 응답
  ai/                   # AI 작업: gateway(가드 → provider → 감사 로그), guard, prompts, competency, screening, followups, scoring
  live/                 # 실시간 전사: hub(STT → 비식별화 → SSE), audio(오디오 소스, 지금은 대본 읽는 가상 지원자)
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
    ocr/paddle.py, ocr/tesseract.py  # 로컬 OCR (PP-OCRv5 한국어 CPU, Tesseract kor+eng)
    isolated.py         # 네이티브 엔진을 작업 프로세스에서 돌리기 (PaddleOCR: 그 DLL이 faster-whisper와 충돌)
    samples/documents/  # 서류 읽기 연결 테스트용 가상 이력서
    fake.py             # 자격증명 없이 도는 구현 (speed로 지연 흉내)
    fake_tasks.py       # fake LLM이 앱 프롬프트에 규칙으로 답하는 부분 (모양만 그럴듯, 품질 아님)
migrations/versions/    # Alembic 0001~0005
scripts/
  seed_demo.py          # 데모 데이터 시드
  grant_admin.py        # 면접관에게 관리자 권한 (0004 이전 DB용, SSO 전까지)
  bench_whisper.py      # Whisper 크기별 속도·메모리·CER·스트리밍 지연 측정
  bench_ocr.py          # OCR 엔진별 쪽당 시간·메모리·CER 측정
  check_leaks.py        # 비식별화 누출 검수 (텍스트 샘플 / --documents 파일 샘플, --ocr로 OCR 포함 / --report 검토 리포트)
  fake_recruiting_site.py  # 가짜 채용 사이트: 서명된 지원서 이벤트 약 500건(중복·순서 바뀜·철회·일부러 넣은 오류), 처리 결과·시간 보고
  make_resume_fixtures.py  # 가상 이력서 31건과 정답 목록 생성 (hwp_writers.py: HWP 5.0·HWPX 쓰기)
  export_mock_data.mjs  # 프론트 모의 데이터 → src/interview_assistant/demo/mock_data.json
tests/
  fixtures/deid_samples.yaml  # 합성 텍스트 샘플 20건과 정답 목록
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

## 실시간 전사

`live/hub.py`: 지원자 오디오 → 세션이 고정한 스트리밍 STT → 비식별화 → SSE(부분·확정 전사, 답변 닫힘). 확정 구간만 저장하고 원문은 원본 영역(`QAItem.answer_text`)에만 둔다.

- 실제 오디오(마이크·WebRTC, 11단계) 전까지는 `live/audio.py`의 가상 지원자가 데모 대본을 텍스트로 보내고 fake STT가 받아 적는다. 속도는 `speed`(providers.fake.yaml)와 `IA_DEMO_SPEED`.
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
