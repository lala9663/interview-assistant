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
| [ai-models.md](ai-models.md) | 관리자 > 모델 설정 사용법, 로컬 Whisper 설치·다운로드·테스트 |
| [model-selection.md](model-selection.md) | 모델 선택 기준, 답변→꼬리질문 간격 예상, STT 선택지, 면접 방식별 오디오·화자 구분, 회사 확인 항목 |
| [whisper-benchmark.md](whisper-benchmark.md) | 이 노트북에서 잰 Whisper 크기별 속도·메모리·정확도 |

작성 예정: 역량 사전 v1 (Phase 1, 대상 직군 확정 후).
