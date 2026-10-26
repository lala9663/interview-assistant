# interview-assistant

JD 기반 서류 선별, 실시간 면접 보조(STT + 꼬리질문), 평점, 면접관 기록, 스케줄 매칭을 하나로 묶는 AI 면접 어시스턴트 PoC.

- 업무정의서: https://claude.ai/artifact/KHpkqy2oKKChicmheA2byK
- 구현 순서: https://claude.ai/artifact/4FK2UfGeYhV1CVscCVaTP4 (저장소 사본 [docs/implementation-order.md](docs/implementation-order.md))

## 기능

| 화면 | 요구사항 | 내용 |
| --- | --- | --- |
| 공고·역량 사전 | FR-02 | JD로 역량과 1~5점 행동 기준(BARS) 초안 생성, 검토 후 버전으로 확정 |
| 서류 선별 | FR-01·03 | 서류 업로드 → 텍스트 추출 → 비식별화 → 프로필 구조화·적합도와 근거. 통과·탈락은 사람이 정함 |
| 실시간 면접 | FR-04~08 | 지원자 카드, 실시간 전사, 꼬리질문 후보 스트리밍, Q&A 기록, 메모. 녹음 동의가 없으면 수기 모드 |
| 평가 | FR-07·08 | AI 참고 점수(근거 인용 필수)와 면접관 점수를 나란히, 합산하지 않음 |
| 면접관 스케줄 | FR-09 | 가용 시간 입력, 공통 빈 시간과 후보 시간 |
| 관리자 > 모델 설정 | | 역할별 AI 모델 선택·테스트·재시작 없는 교체·이력·되돌리기 |

## 원칙

- 지원자 식별 정보는 원본 영역에만 둔다. 화면과 LLM에는 비식별 텍스트만 가고, 호출 직전에 가드가 다시 확인한다.
- 음성 원본은 외부로 보내지 않는다.
- 모든 AI 호출과 주요 행동은 감사 로그에 남긴다.
- LLM / STT / 임베딩 / 화자분리는 provider 인터페이스로만 부르고, 관리자 화면에서 교체한다.

## 빠른 시작

```bash
uv sync --extra whisper
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
| [docs/deidentification.md](docs/deidentification.md) | 비식별화 설정·탐지 규칙, 서류 파일, 누출 검수와 검토 리포트 |
| [docs/frontend.md](docs/frontend.md) | 프론트 스택, 모의·연결 모드, 검사, 의존성 규칙 |
| [docs/ai-models.md](docs/ai-models.md) | 관리자 > 모델 설정 사용법, 로컬 Whisper 설치·다운로드·테스트 |
| [docs/model-selection.md](docs/model-selection.md) | 모델 선택 기준, 답변→꼬리질문 간격 예상, STT 선택지, 면접 방식별 오디오·화자 구분, 회사 확인 항목 |
| [docs/whisper-benchmark.md](docs/whisper-benchmark.md) | 이 노트북에서 잰 Whisper 크기별 속도·메모리·정확도 |
| [docs/implementation-order.md](docs/implementation-order.md) | 13단계 구현 순서와 체크리스트 |

## 구조

```
config/        provider 기본값(YAML), 비식별화 설정·사전
src/interview_assistant/
  api/         REST·SSE API          ai/          AI 작업 (gateway, prompts, 채점 …)
  ai_models/   모델 설정·교체          providers/   provider 인터페이스·구현·카탈로그
  deid/        비식별화              documents/   서류 텍스트 추출
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
- 남은 것: 3단계 실제 LLM 연결과 품질 검증, 10~11단계 오디오(마이크·WebRTC, 사후 전사), 로그인(SSO), 사내 허용 모델 확인.

자세한 체크리스트는 [docs/implementation-order.md](docs/implementation-order.md).
