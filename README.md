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
  db.py                 # 엔진, 세션 팩토리
  main.py               # FastAPI 앱
  models/               # ORM 모델 13개 (업무정의서 6장)
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

## 진행 순서

[docs/implementation-order.md](docs/implementation-order.md) 참조. 현재 1단계(도메인 모델·DB) 완료, 다음은 2단계 비식별화.
