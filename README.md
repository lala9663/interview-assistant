# interview-assistant

JD 기반 서류 선별, 실시간 면접 보조(STT + 꼬리질문), 평점, 면접관 기록, 스케줄 매칭을 하나로 묶는 AI 면접 어시스턴트 PoC.

- 업무정의서: https://claude.ai/artifact/KHpkqy2oKKChicmheA2byK
- 구현 순서: https://claude.ai/artifact/4FK2UfGeYhV1CVscCVaTP4 (저장소 사본 [docs/implementation-order.md](docs/implementation-order.md))

## 기능

| 화면 | 요구사항 | 내용 |
| --- | --- | --- |
| 공고·역량 사전 | FR-02 | 공고별 전형 차수(1차 직무 면접, 2차 임원 면접 …)와 차수마다 진행 방식·권장 면접관 수·이전 차수 점수 공개 설정. 차수별로 JD와 차수 목적에서 역량과 1~5점 행동 기준(BARS) 초안 생성, 검토 후 버전으로 확정, 사전 질문 편집·AI 초안(이전 차수 질문 반복 없음) |
| 서류 선별 | FR-01·03 | 서류 업로드 또는 채용 사이트 연동 → 서류 읽기(쪽마다 텍스트 층 또는 OCR. PDF·DOCX·PPTX·HTML·HWP·HWPX·구형 .doc/.ppt·JPG/PNG) → 비식별화 → 프로필 구조화·적합도와 근거. 통과·탈락은 사람이 정함. 목록에 수신 경로와 진행(서류 ✓ · 1차 ✓ · 2차 ●), 차수 필터, 상세에 서류 → 각 차수 → 최종 단계와 차수 결정 이력 |
| 실시간 면접 | FR-04~08 | 지원자 카드(2차부터 이전 차수 요약: 확인이 필요한 점·메모, 점수는 공고 설정이 공개일 때만), 면접실 마이크(말소리만 전사, 답변 끝 자동 판정, 질문 중/답변 듣는 중 전환, 막히면 HTTP로, 문제는 짧은 코드로, 진단용 샘플 음성), 실시간 전사, 꼬리질문 후보: 검수된 질문 은행 후보가 먼저, AI 후보가 이어서 스트리밍(출처 배지, 이 면접·이전 차수에서 한 질문과 같은 뜻은 걸러냄), 이전 차수 답변으로 만든 이어 질문, Q&A 기록, 메모. 녹음 동의가 없으면 수기 모드 |
| 질문 은행·평점 기준 | FR-06·07 | 직군·역량·차수별 검수 질문(초안·승인·폐기, 금지 질문 경고, CSV 가져오기)과 역량별 1~5점 가상 기준 답변. 승인한 것만 BGE-M3로 임베딩해 꼬리질문 후보·AI 예시·채점 기준점·역량 사전 초안 예시로 쓴다. 지원자 답변은 임베딩·예시로 쓰지 않고, 기준 예시와의 유사도로 채점하지 않는다 |
| 평가 | FR-07·08 | AI 참고 점수(근거 인용 필수)와 면접관 점수를 나란히, 합산하지 않음. 면접관 전원 제출 뒤 사람이 N차 결정(합격·보류·불합격, 사유 필수, 바꾸면 이력), 다음 차수에서 확인할 점(면접관·AI). 마지막 차수 합격 = 최종 합격 후보(공식 결과는 채용 사이트) |
| 면접관 스케줄 | FR-09 | 가용 시간 입력, 공통 빈 시간과 후보 시간, 차수부터 고르는 면접 잡기(1차는 서류 통과자, N차는 이전 차수 합격자만) |
| 관리자 > 모델 설정 | | 역할별 AI 모델, 서류 읽기 도구(읽기 방식, OCR 엔진, PDF·HWP 읽기, 구형 오피스 변환), 음성 입력(VAD, 답변 끝 판정, 서버 잡음 억제) 선택·테스트·재시작 없는 교체·이력·되돌리기, 임베딩 색인 상태·재색인, 면접 뒤 녹음 재전사 |
| 관리자 > 꼬리질문 지표 | | 출처별(질문 은행 / AI) 채택률, 첫 후보까지 시간, 이미 한 질문이라 걸러낸 수 |
| 관리자 > 연동 현황 | | 채용 사이트가 보낸 지원서 이벤트(제출·수정·철회)와 처리 결과·실패 사유, 공고별 건수, 실패 다시 처리 |
| 에이전트 플랫폼 (MCP) | | 사내에 들어올 에이전트 플랫폼(FabriX Agent Studio 등, 미정)이 쓰는 MCP 서버: 읽기 도구 13개(공고·차수, 지원자 순위·요약, 평가·결정 이력, 공통 빈 시간, 질문 은행, 연동 실패 …)와 제안 도구 3개(면접 잡기, 서류 통과·탈락, 차수 결정은 웹에서 사람이 확인). 질문한 사람의 권한, 비식별 결과만 |

## 원칙

- 지원자 식별 정보는 원본 영역에만 둔다. 화면과 LLM에는 비식별 텍스트만 가고, 호출 직전에 가드가 다시 확인한다.
- 음성 원본은 외부로 보내지 않는다. 서류 속 그림은 OCR로 텍스트만 꺼내 비식별화하고, 그림을 모델로 보내지 않는다.
- 모든 AI 호출과 주요 행동은 감사 로그에 남긴다. 에이전트(MCP) 호출은 읽기까지 호출마다 남는다.
- 에이전트 플랫폼은 질문한 사람의 권한으로 읽고 제안만 한다. 바꾸는 일은 웹에서 사람이 확인한다. 공개 챗봇에 실제 데이터를 붙이지 않는다.
- LLM / STT / 임베딩 / 화자분리 / OCR은 provider 인터페이스로만 부르고, 관리자 화면에서 교체한다.
- 벡터로 저장하는 것은 회사가 쓴 텍스트(승인된 질문 은행, 평점 기준 예시, 확정 역량 사전)뿐이다. 지원자 답변은 꼬리질문 검색 때 가드를 거쳐 임베딩만 하고 저장하지 않는다.

## 빠른 시작

```bash
uv sync --extra whisper --extra ocr --extra embedding
cp .env.example .env            # IA_ENCRYPTION_KEY를 채운다 (docs/setup.md)
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset
uv run uvicorn interview_assistant.main:app --reload
```

```bash
cd frontend && npm ci
npm run dev:api                 # 백엔드에 연결 → http://localhost:5173
npm run dev                     # 또는 백엔드 없이 모의 API로
```

처음에는 모든 AI가 fake provider로 돈다(`IA_PROVIDERS_FILE=config/providers.fake.yaml`). 로그인 전까지는 시드의 김서연(E24017, 관리자)이 로그인한 면접관이다.

```bash
uv run pytest                   # 백엔드 (외부 네트워크 없음)
cd frontend && npm run check    # 타입 검사 + 린트 + 테스트 + 빌드
```

## 문서

| 문서 | 내용 |
| --- | --- |
| [docs/setup.md](docs/setup.md) | 설치, 환경변수, DB·마이그레이션, 시드, 테스트 |
| [docs/architecture.md](docs/architecture.md) | 저장소 구조, AI 호출 흐름(가드·감사 로그), 실시간 전사, 업로드 |
| [docs/api-contract.md](docs/api-contract.md) | 프론트 ↔ 백엔드 REST·SSE 계약, 모델 결정, 남은 과제 |
| [docs/site-intake-spec.md](docs/site-intake-spec.md) | 채용 사이트 → 이 시스템 지원서 연동 명세(채용 시스템 부서용): 엔드포인트, 필드, 서명, 재시도, 오류 코드, 받지 않는 항목, 확인 목록 |
| [docs/deidentification.md](docs/deidentification.md) | 비식별화 설정·탐지 규칙, 서류 파일, 누출 검수와 검토 리포트 |
| [docs/frontend.md](docs/frontend.md) | 프론트 스택, 모의·연결 모드, 검사, 의존성 규칙 |
| [docs/ai-models.md](docs/ai-models.md) | 관리자 > 모델 설정 사용법, 로컬 Whisper·OCR 설치·다운로드·테스트 |
| [docs/document-reading.md](docs/document-reading.md) | 서류 읽기: 형식별 지원 현황, 쪽마다 텍스트·OCR 고르는 규칙, 깨짐·증명사진 판정, OCR 오독 대책, HWP 도구 결정, 알려진 한계 |
| [docs/model-selection.md](docs/model-selection.md) | 모델 선택 기준, 답변→꼬리질문 간격 예상, STT 선택지, 면접 방식별 오디오·화자 구분, 임베딩(BGE-M3) 결정, 회사 확인 항목 |
| [docs/question-bank.md](docs/question-bank.md) | 질문 은행·평점 기준 예시: 어디에 쓰고 쓰지 않나, 금지 질문 규칙 목록, CSV 형식 |
| [docs/embedding-benchmark.md](docs/embedding-benchmark.md) | 이 노트북에서 잰 BGE-M3 속도·메모리, 한국어 검색 적중률, 임계값 보정 |
| [docs/audio-input.md](docs/audio-input.md) | 실시간 면접 마이크 입력: 브라우저 설정·전송(WebSocket, HTTP 대체), 진단용 샘플 음성, VAD, 답변 끝 판정 비교와 기본값, 답변 중 미리 임베딩, 오류 코드 목록, 서버 잡음 억제, GPU 없을 때 재전사, 이 노트북 측정, 사내 환경별 설정 |
| [docs/whisper-benchmark.md](docs/whisper-benchmark.md) | 이 노트북에서 잰 Whisper 크기별 속도·메모리·정확도 |
| [docs/ocr-benchmark.md](docs/ocr-benchmark.md) | 이 노트북에서 잰 PaddleOCR·Tesseract 쪽당 속도·메모리·한국어 정확도 |
| [docs/reference/](docs/reference/README.md) | 참고 자료: 라이브러리·모델·클라우드 서비스(라이선스·비용·데이터 위치), STT·화자분리 비교, 음성 품질, 용어집 |
| [docs/internal-environment-checklist.md](docs/internal-environment-checklist.md) | 사내 환경 확인 체크리스트: 외부 개발 환경을 사내와 맞추기 위해 손으로 채워 오는 양식(사내 LLM, OS·Python, Docker·GPU, DB, 네트워크·미러, 사용자 PC, 인증·연동, 반입·반출 규정) |
| [docs/agent-integration.md](docs/agent-integration.md) | 사내 에이전트 플랫폼 연동(MCP 서버): 구조, 도구 목록, 보안 규칙(질문한 사람 권한·비식별 출력·웹 확인·감사 로그·플랫폼 LLM으로 가는 데이터), 사용자 신원을 갈아 끼우는 곳, 플랫폼 담당 부서 확인 목록, 연결 예시 |
| [docs/implementation-order.md](docs/implementation-order.md) | 13단계 구현 순서와 체크리스트 |

## 구조

```
config/        provider 기본값(YAML), 비식별화 설정·사전
src/interview_assistant/
  api/         REST·SSE API          ai/          AI 작업 (gateway, prompts, 채점 …)
  ai_models/   모델 설정·교체          providers/   provider 인터페이스·구현·카탈로그
  intake/      지원서 수신 (업로드·채용 사이트 → 처리 함수 하나)
  retrieval/   검색 (질문 은행·기준 예시·역량 사전 벡터, 재색인)
  agent/       MCP 서버 (사내 에이전트 플랫폼용, REST API를 부르는 얇은 계층)
  deid/        비식별화              documents/   서류 읽기 (텍스트·OCR)
  live/        실시간 전사            models/      ORM 모델
migrations/    Alembic                scripts/     시드, 누출 검수, Whisper 측정 …
tests/         백엔드 테스트·픽스처      frontend/    면접관 UI (Vue 3)
docs/          문서
```

자세한 구조는 [docs/architecture.md](docs/architecture.md).

## 진행 상황

- 2단계 비식별화: 구현 완료, 사용자 확인(토큰 형식, 사전, 검토 리포트로 20건 수동 검수) 대기.
- 4~9단계: API·저장·화면을 fake provider로 구현(2026-10-23).
- 관리자 > 모델 설정과 첫 실제 provider인 로컬 Whisper STT(2026-10-25).
- 서류 읽기 확장(2026-10-26): 쪽마다 텍스트 층·OCR 자동 선택(깨짐 판정 포함), 로컬 OCR(PaddleOCR PP-OCRv5 한국어, Tesseract), HWP·HWPX, 구형 .doc/.ppt(LibreOffice), JPG·PNG, 관리자 화면 "서류 읽기" 묶음. 가상 이력서 31건 OCR 포함 누출 0.
- 면접 여러 차수(2026-10-27): 공고별 전형 차수, 차수별 역량 사전·사전 질문, 차수 결정(사람, 이력), 다음 차수 대상 규칙, 이전 차수 요약(점수는 공고 설정), 이전 차수 Q&A를 참고하는 꼬리질문·이어 질문, AI 확인할 점.
- 질문 은행과 임베딩 검색(2026-10-27): 로컬 BGE-M3(밀집 + 희소, ONNX Runtime), 질문 은행·평점 기준 예시 관리와 금지 질문 경고, 질문 은행 후보가 먼저 뜨는 꼬리질문, 이미 한 질문 거르기, 채점 기준점, 비슷한 공고의 역량 사전 참고, 모델 교체 시 재색인, 꼬리질문 지표. 한국어 평가 세트 상위 3개 적중 94.6%.
- 에이전트 플랫폼 연동(2026-10-28): MCP 서버(stdio·streamable HTTP, Python MCP SDK 2.3), 읽기 13·제안 3 도구, 질문한 사람의 자격증명(지금은 개발용 토큰, 신원 확인은 교체 가능), 에이전트 쓰기 차단, 호출마다 감사 로그. 플랫폼은 미정(FabriX Agent Studio 등).
- 실시간 면접 마이크 입력(2026-10-28): 브라우저 마이크(AudioWorklet 16kHz PCM16, WebSocket, 막히면 HTTP 청크), 진단용 샘플 음성, Silero VAD로 말소리만 STT에, 답변 끝 판정(침묵 기준·Smart Turn v3.2, 생각하는 멈춤이 든 한국어 32건으로 비교해 Smart Turn 1초·0.8을 기본으로), 이어 말하면 같은 답에 붙이기, 질문 중/답변 듣는 중 전환, 답변 중 미리 임베딩, 동의한 면접만 원본 영역 WAV 녹음, 면접 뒤 녹음 재전사, 오류 코드.
- 실행 위치(2026-10-28): 2026-10-21에 PoC를 GCP에서 하기로 정했으나 철회했다. 실행 위치(사내 서버, 사내 클라우드, 에이전트 플랫폼 안)는 미정이고, 로컬에서 먼저 돌리며 사내 에이전트 플랫폼에 MCP로 붙인다. LLM은 사내 LLM(플랫폼 제공) 또는 사내에 설치한 오픈 웨이트 모델에 OpenAI 형식 API로 붙인다(OpenAI 서비스는 쓰지 않음, 모델 서버 위치 미정).
- 채용 사이트 연동 수신(2026-10-26): 서명된 이벤트 수신 API와 연동 명세, 통로와 분리된 처리 함수, 백그라운드 큐, 연동 현황 화면. 가짜 채용 사이트로 500건 검증. 실제 사이트 연결은 승인·네트워크 확인 뒤.
- 남은 것: 3단계 실제 LLM 연결과 품질 검증, 최종 결과를 채용 사이트에 반영하는 방식(지금은 담당자가 사이트에 직접 기록), 한글 프로그램으로 저장한 실제 HWP 샘플 확인, WebRTC(비대면)·마이크 두 개·재전사 결과의 질문별 반영, 실제 면접 녹음으로 답변 끝 판정 다시 재기, 로그인(SSO, 에이전트 신원 포함), 에이전트 플랫폼 선정과 플랫폼 담당 부서 확인·정보보호 승인, 실행 위치와 사내 허용 모델 확인, 채용 사이트 실제 연결(또는 대안인 압축 파일 일괄 가져오기).

자세한 체크리스트는 [docs/implementation-order.md](docs/implementation-order.md).
