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
src/interview_assistant/
  config.py             # 설정 로더 (env + providers.yaml)
  main.py               # FastAPI 앱
  providers/
    base.py             # LLMProvider, STTProvider, EmbeddingProvider, DiarizationProvider
    registry.py         # impl 이름 -> 구현 클래스
    fake.py             # 테스트용 구현
tests/
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

## 다음 단계

1. `providers/llm/anthropic_vertex.py`, `providers/stt/google_stt_v2.py` 구현
2. DB 스키마 (업무정의서 6장) + Alembic 마이그레이션
3. 서류 선별(FR-01) 파이프라인
