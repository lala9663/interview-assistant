# 문서 목록

> 다루는 것: `docs/`의 모든 문서와 누가 무엇부터 읽으면 되는지, 주제마다 어느 문서가 기준인지.
>
> 상태: 구현됨 · 확인: 2026-10-30

저장소 밖 문서(claude.ai의 업무정의서, 구현 순서 원본, 사내 환경 체크리스트 원본)는 사내에서 열리지 않는다. 사내에서는 이 폴더만 본다. 구현 순서와 체크리스트는 이 폴더에 사본이 있다.

## 처음 보는 사람

| 문서 | 무엇을 알 수 있나 |
| --- | --- |
| [../README.md](../README.md) | 이 시스템이 무엇인지, 9개 요구사항의 상태, 빠른 시작 |
| [implementation-order.md](implementation-order.md) | 13단계 구현 순서와 단계마다 한 것·남은 것 (체크리스트) |
| [model-selection.md](model-selection.md) | 왜 이 모델들을 골랐나: 역할별 기준, 꼬리질문까지 걸리는 시간, 면접 방식별 오디오, 정한 것과 미룬 것 |
| [architecture.md](architecture.md) | 코드가 어디 있고, AI 호출·검색·실시간 전사·지원서 수신이 어떻게 흐르나 |
| [reference/glossary.md](reference/glossary.md) | 용어집: 문서와 코드의 표기와 위치 |

## 개발자

| 문서 | 무엇을 알 수 있나 |
| --- | --- |
| [setup.md](setup.md) | 설치, 환경변수, DB·마이그레이션, 시드, 테스트, 가짜 채용 사이트 |
| [api-contract.md](api-contract.md) | 프론트 ↔ 백엔드 REST·SSE·WebSocket 계약, DB 모델 결정(Alembic), 남은 과제 |
| [frontend.md](frontend.md) | 프론트 스택, 화면 목록, 모의 API 모드와 백엔드 연결 모드, 검사, 의존성 규칙 |
| [deidentification.md](deidentification.md) | 비식별화 코드·설정, 탐지 규칙, 서류 파일 처리, 누출 검수와 검토 리포트 |
| [document-reading.md](document-reading.md) | 서류 읽기: 형식별 지원 현황, 쪽마다 텍스트·OCR 고르는 규칙, 깨짐·증명사진 판정, HWP 도구, 알려진 한계 |
| [audio-input.md](audio-input.md) | 실시간 면접 마이크: 브라우저 설정, WebSocket·HTTP 전송, VAD, 답변 끝 판정, 오류 코드, 면접 뒤 재전사, 사내 환경별 설정 |
| [question-bank.md](question-bank.md) | 질문 은행·평점 기준 예시를 어디에 쓰고 쓰지 않나, 금지 질문 규칙, CSV 형식 |

## 운영·사내 반입

| 문서 | 무엇을 알 수 있나 |
| --- | --- |
| [ai-models.md](ai-models.md) | 관리자 > 모델 설정 사용법, provider별 설치·옵션(사내 모델 서버, Claude API, Whisper, BGE-M3, 음성 입력, OCR) |
| [internal-environment-checklist.md](internal-environment-checklist.md) | 첫 반입 전에 사내에서 손으로 채워 오는 양식(사내 LLM, OS·Python, GPU, DB, 네트워크, 사용자 PC, 인증, 반입·반출 규정) |
| [agent-integration.md](agent-integration.md) | 사내 에이전트 플랫폼 연동(MCP 서버): 실행, 도구 목록, 보안 규칙, 사용자 신원을 바꿔 끼우는 곳, 플랫폼 담당 부서 확인 목록 |
| [site-intake-spec.md](site-intake-spec.md) | 채용 사이트 → 이 시스템 지원서 연동 명세(채용 시스템 부서용): 엔드포인트, 필드, 서명, 재시도, 오류 코드, 받지 않는 항목 |

사내에서 문제가 나면 화면의 오류 코드를 적어 온다. 마이크·전사 코드는 [audio-input.md](audio-input.md) 6장, 채용 사이트 연동 코드는 [site-intake-spec.md](site-intake-spec.md) 8장.

## 참고 자료

| 문서 | 무엇을 알 수 있나 |
| --- | --- |
| [whisper-benchmark.md](whisper-benchmark.md) | 이 노트북에서 잰 Whisper 크기별 속도·메모리·정확도 |
| [ocr-benchmark.md](ocr-benchmark.md) | 이 노트북에서 잰 PaddleOCR·Tesseract 쪽당 속도·메모리·정확도 |
| [embedding-benchmark.md](embedding-benchmark.md) | 이 노트북에서 잰 BGE-M3(fp32·int8) 속도·메모리, 한국어 검색 적중률, 꼬리질문 지연 |
| [reference/README.md](reference/README.md) | 참고 자료 폴더 안내 |
| [reference/libraries.md](reference/libraries.md) | 쓰거나 검토한 라이브러리·모델·클라우드 서비스의 라이선스·비용·데이터 위치·상태 |
| [reference/llm.md](reference/llm.md) | 사내에서 돌릴 오픈 웨이트 LLM 비교와 작업별 권장 |
| [reference/stt.md](reference/stt.md) | 한국어 면접 전사에 쓸 수 있는 STT 비교 |
| [reference/diarization.md](reference/diarization.md) | 화자분리 방법 비교 |
| [reference/audio-quality.md](reference/audio-quality.md) | 마이크부터 전사 품질을 좌우하는 것, 답변 끝 판단, 품질 재는 법 |

## 주제마다 기준이 되는 문서

같은 내용을 여러 문서에 다시 쓰지 않는다. 아래 문서가 그 주제의 기준이고, 다른 문서는 링크만 건다.

| 주제 | 기준 문서 |
| --- | --- |
| 어떤 모델을 왜 골랐나, 미룬 결정 | [model-selection.md](model-selection.md) |
| 관리자 화면 사용법, provider 옵션 | [ai-models.md](ai-models.md) |
| API 경로·필드·오류, DB 모델 결정 | [api-contract.md](api-contract.md) |
| 마이크·VAD·답변 끝 판정·오류 코드 | [audio-input.md](audio-input.md) |
| 비식별화 규칙 | [deidentification.md](deidentification.md) |
| 서류 형식과 OCR 규칙 | [document-reading.md](document-reading.md) |
| 측정값 | `*-benchmark.md` 세 개와 [audio-input.md](audio-input.md) 9장 |
| 라이선스·가격·외부 서비스 | [reference/libraries.md](reference/libraries.md) |
| 진행 상황 | [implementation-order.md](implementation-order.md) |

## 문서 머리 규칙

모든 문서는 제목 바로 아래에 세 가지를 적는다.

- **다루는 것**: 한두 문장.
- **상태**: 결정됨(정했고 아직 코드와 상관없는 것), 구현됨(코드에 있음), 계획(아직 없음). 섞여 있으면 "구현됨, 일부 계획"처럼 쓴다.
- **확인**: 코드와 맞춰 본 날. 바깥 출처(가격·라이선스)를 따로 확인한 날은 본문에 적는다.

날짜가 붙은 결정 이력은 "왜"를 설명할 때만 남기고 짧게 쓴다.

작성 예정: 역량 사전 v1 (대상 직군을 정한 뒤).
