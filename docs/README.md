# docs

- 업무정의서 (요구사항, 스택, 보안, 단계): https://claude.ai/artifact/KHpkqy2oKKChicmheA2byK
- 구현 순서 (13단계, 6주 타임라인, 체크리스트): [implementation-order.md](implementation-order.md) · 원본 doc: https://claude.ai/artifact/4FK2UfGeYhV1CVscCVaTP4

| 문서 | 내용 |
| --- | --- |
| [setup.md](setup.md) | 설치, 환경변수, DB·마이그레이션, 시드, 테스트 |
| [architecture.md](architecture.md) | 저장소 구조, AI 호출 흐름(가드·감사 로그), 실시간 전사, 업로드 |
| [api-contract.md](api-contract.md) | 프론트 ↔ 백엔드 REST·SSE 계약, 모델 결정, 남은 과제 |
| [deidentification.md](deidentification.md) | 비식별화 설정·탐지 규칙, 서류 파일, 누출 검수와 검토 리포트 |
| [frontend.md](frontend.md) | 프론트 스택, 모의·연결 모드, 검사, 의존성 규칙 |
| [ai-models.md](ai-models.md) | 관리자 > 모델 설정 사용법, 로컬 Whisper·OCR 설치·다운로드·테스트 |
| [document-reading.md](document-reading.md) | 서류 읽기: 형식별 지원 현황, 쪽마다 텍스트·OCR 고르는 규칙, 깨짐·증명사진 판정, OCR 오독 대책, HWP 도구 결정, 알려진 한계 |
| [model-selection.md](model-selection.md) | 모델 선택 기준, 답변→꼬리질문 간격 예상, STT 선택지, 면접 방식별 오디오·화자 구분, 임베딩(BGE-M3) 결정, 회사 확인 항목 |
| [question-bank.md](question-bank.md) | 질문 은행·평점 기준 예시: 어디에 쓰고 쓰지 않나, 금지 질문 규칙 목록, CSV 형식 |
| [embedding-benchmark.md](embedding-benchmark.md) | 이 노트북에서 잰 BGE-M3 속도·메모리, 한국어 검색 적중률, 임계값 보정 |
| [whisper-benchmark.md](whisper-benchmark.md) | 이 노트북에서 잰 Whisper 크기별 속도·메모리·정확도 |
| [ocr-benchmark.md](ocr-benchmark.md) | 이 노트북에서 잰 PaddleOCR·Tesseract 쪽당 속도·메모리·한국어 정확도 |
| [agent-integration.md](agent-integration.md) | 사내 에이전트 플랫폼 연동(MCP 서버): 구조, 도구 목록, 보안 규칙, 사용자 신원을 갈아 끼우는 곳, 플랫폼 담당 부서 확인 목록, 연결 예시 |
| [reference/](reference/README.md) | 참고 자료: 라이브러리·모델·클라우드 서비스(라이선스·비용·데이터 위치), STT·화자분리 비교, 음성 품질, 용어집 |

작성 예정: 역량 사전 v1 (Phase 1, 대상 직군 확정 후).
