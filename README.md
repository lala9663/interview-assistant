# interview-assistant

사내 채용 면접을 돕는 AI 면접 어시스턴트 PoC다. JD로 서류를 선별하고, 면접 중 전사와 꼬리질문 후보를 띄우고, AI 참고 점수와 면접관 기록을 나란히 남기고, 면접관 일정을 맞춘다.

- 합격·불합격은 언제나 사람이 정한다. AI 점수는 참고용이고 면접관 점수와 합산하지 않는다.
- LLM에는 비식별 텍스트만 간다. 이름·연락처는 원본 영역에 암호화해 두고, 호출 직전에 가드가 한 번 더 본다.
- 음성은 서버 밖으로 나가지 않는다(로컬 STT). 서류 속 그림은 OCR로 글자만 꺼내고 모델로 보내지 않는다.
- 모든 AI 모델은 provider로 갈아 끼운다. 어떤 모델을 쓸지는 관리자 화면에서 정한다.

실행 위치(사내 서버, 사내 클라우드, 에이전트 플랫폼 안)는 아직 정하지 않았다. GCP에서 돌리지 않는다. 사내 에이전트 플랫폼에는 MCP 서버로 붙는다.

## 9개 요구사항과 상태

2026-10-30 main 기준. 지금은 AI가 fake provider로 돌아 흐름만 확인했고, 실제 LLM을 붙인 품질 검증이 남았다.

| 번호 | 요구사항 | 상태 | 화면 |
| --- | --- | --- | --- |
| FR-01 | JD 기반 서류 선별, 프로필 저장 | 구현됨. 업로드와 채용 사이트 연동(가짜 사이트로 검증), PDF·DOCX·PPTX·HTML·HWP·HWPX·구형 .doc/.ppt·JPG/PNG, 쪽마다 텍스트 또는 OCR | 서류 선별 |
| FR-02 | 직군별 역량 사전 | 구현됨. 차수별 역량과 1~5점 행동 기준(BARS) AI 초안 → 사람이 확정 | 공고·역량 사전 |
| FR-03 | 선별한 서류 기억 | 구현됨. 프로필·적합도·근거를 DB에, 서류 → 각 차수 → 최종 진행 | 서류 선별 |
| FR-04 | 면접 중 지원자 특징 기억 | 구현됨. 지원자 카드, 메모, 2차부터 이전 차수 요약 | 실시간 면접 |
| FR-05 | 실시간 면접, 대면·비대면 | 대면 구현됨(브라우저 마이크, 한 마이크면 질문 중/답변 듣는 중 전환). 비대면(WebRTC)은 계획 | 실시간 면접 |
| FR-06 | 질문, 꼬리질문, Q&A 저장, STT | 구현됨. 사전 질문, 질문 은행 후보 먼저 + AI 후보 스트리밍, 로컬 Whisper 전사, 면접 뒤 재전사 | 실시간 면접, 질문 은행 |
| FR-07 | 객관적인 답변 평점 | 구현됨. AI 참고 점수(근거 인용 필수, 3회 중앙값, 평점 기준 예시). 면접관 점수와의 일치도 검증은 실제 LLM 뒤 | 평가 |
| FR-08 | 면접관 기록 | 구현됨. 면접관 점수·코멘트, 메모, 차수 결정과 이력, 다음 차수에서 확인할 점 | 평가 |
| FR-09 | 면접관 일정, 빈 시간 맞추기 | 구현됨. 가용 시간 입력, 공통 빈 시간, 면접 잡기. 사내 캘린더 연동은 계획 | 면접관 스케줄 |

남은 큰 일: 실제 LLM 연결(사내 모델 서버), 로그인(SSO), 비대면 WebRTC, 채용 사이트 실제 연결, 실행 위치 결정. 단계별 체크리스트는 [docs/implementation-order.md](docs/implementation-order.md).

## 빠른 시작

필요한 것: Python 3.12와 [uv](https://docs.astral.sh/uv/), Node 24 이상. 자세한 설치와 환경변수는 [docs/setup.md](docs/setup.md).

```bash
uv sync --extra whisper --extra ocr --extra embedding --extra agent --extra denoise
cp .env.example .env
```

`.env`에 `IA_ENCRYPTION_KEY`를 채운다(만드는 법은 setup.md). 사내 모델 서버가 아직 없으면 첫 기동 전에 `IA_PROVIDERS_FILE=config/providers.fake.yaml`로 바꾼다. 그러면 모든 AI가 fake로 돈다.

```bash
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset
uv run uvicorn interview_assistant.main:app --reload       # http://localhost:8000
```

```bash
cd frontend
npm ci
npm run dev:api        # 백엔드에 연결 → http://localhost:5173
npm run dev            # 또는 백엔드 없이 모의 API로
```

로그인(SSO)이 붙기 전까지는 시드의 김서연(E24017, 관리자)이 로그인한 면접관이다. 테스트는 `uv run pytest`와 `frontend/`에서 `npm run check`.

## 모델은 어디서 정하나

화면 **관리자 > 모델 설정**(`/admin/models`)에서 역할마다 provider를 고르고, 연결 테스트를 한 뒤 재시작 없이 적용한다. 이력에서 되돌릴 수 있다. `config/providers.yaml`은 새 DB가 처음 기동할 때의 기본값일 뿐이다. 사용법은 [docs/ai-models.md](docs/ai-models.md).

| 역할 | 지금 기본값 | 비고 |
| --- | --- | --- |
| LLM | `open_model_server`: 사내 오픈 웨이트 모델 서버(vLLM·Ollama 등)에 OpenAI 형식 API로 | 사내 모델은 Gemma 4로 예상(확인 필요). OpenAI 서비스는 쓰지 않는다. Claude API(`anthropic_api`)는 외부 개발 테스트용으로만 |
| STT | 로컬 faster-whisper: 실시간 small, 사후 large-v3 + 면접 뒤 녹음 재전사 | GPU가 없어서 실시간은 작게, 기록은 크게 |
| 임베딩 | 로컬 BGE-M3 int8 | 질문 은행 검색과 같은 질문 거르기 |
| 답변 끝 판정 | Smart Turn v3 (1초, 0.8) | 모델 파일이 없으면 침묵 2초 |
| 화자분리 | fake | 면접 흐름에서 쓰지 않는다. 화자는 마이크의 역할 기록으로 붙인다 |
| 서류 읽기 | PaddleOCR(PP-OCRv5 한국어), syhwp, LibreOffice | |

## 저장소 구조

```
config/        provider 첫 기동 기본값(YAML), 비식별화 설정·사전
src/interview_assistant/
  api/         REST·SSE API             ai/          AI 작업 (게이트웨이, 프롬프트, 채점 …)
  ai_models/   관리자 모델 설정·교체      providers/   provider 인터페이스·구현·카탈로그
  intake/      지원서 수신               retrieval/   질문 은행 임베딩 검색
  deid/        비식별화                  documents/   서류 읽기 (텍스트·OCR)
  live/        실시간 전사·마이크          agent/       MCP 서버 (사내 에이전트 플랫폼용)
  models/      ORM 모델
migrations/    Alembic 마이그레이션         scripts/     시드, 누출 검수, 측정 …
tests/         백엔드 테스트              frontend/    면접관 화면 (Vue 3)
docs/          문서
```

자세한 구조는 [docs/architecture.md](docs/architecture.md).

## 문서

모든 문서의 목록과 읽는 순서는 [docs/README.md](docs/README.md).



내부 리뷰: 과제 범위와 다음 미팅 준비
다루는 것: 피플팀 2차 미팅 전 내부 리뷰에서 "필요하다"·"중요하다"고 정한 것, 지금 저장소와 맞춰 볼 점, 다음 미팅까지 할 일.
상태: 결정됨(리뷰 지시 사항), 일부 계획 · 작성 2026-11-10 · 확인: 2026-11-10
회의 녹취(음성 인식) 중 회의실 안 논의만 정리했다. 녹취 품질이 낮아 사람 이름과 일부 용어는 적지 않았다. 회의 날짜는 녹취에 없어서 작성일을 적었다.
1. 리뷰 결론
지금 프로세스 초안은 박스와 흐름도 수준이라 현업보다 고민이 얕아 보인다. 요구사항 범위 안에서 더 깊게 세분화한다.
요청받지 않은 기능(참고 솔루션의 포지션 추천 등)은 과제와 같은 레벨로 그리지 않는다.
다음 미팅은 질의응답이 아니라 결과물(세부 플로우, 범위 정의, 목업)을 보여주는 자리로 쓴다.
2. 필요한 것 (산출물)
