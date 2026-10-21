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
  deid.yaml             # 비식별화: 토큰 형식, 사전 경로, 탐지기 목록, 예외 목록
  deid/                 # 학교·회사 사전 초안 (공개 기관명)
src/interview_assistant/
  config.py             # 설정 로더 (env + providers.yaml)
  crypto.py             # 컬럼 암호화 (Fernet, IA_ENCRYPTION_KEY)
  db.py                 # 엔진, 세션 팩토리
  main.py               # FastAPI 앱
  models/               # ORM 모델 14개 (업무정의서 6장 13개 + 비식별 역매핑)
  deid/                 # 비식별화 (업무정의서 9장)
    deidentifier.py     # 원문 -> 토큰 치환 텍스트. LLM으로 가는 유일한 통로
    detectors/          # 교체 가능한 탐지기: 본인 정보, 정규식, 사전, 형태 패턴, 호칭 붙은 이름, NER 자리
    store.py            # 토큰 발급과 역매핑 저장 (원래 값은 암호화)
    reidentify.py       # 재식별. 역매핑을 복호화하는 유일한 곳, 호출마다 감사 로그
    leaks.py            # 누출 검수 로직
  providers/
    base.py             # LLMProvider, STTProvider, EmbeddingProvider, DiarizationProvider
    registry.py         # impl 이름 -> 구현 클래스
    fake.py             # 테스트용 구현
scripts/
  check_leaks.py        # 비식별화 누출 검수 리포트
tests/
  fixtures/deid_samples.yaml  # 합성 샘플 20건과 정답 목록
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

## 비식별화

LLM에는 `Deidentifier`를 거친 텍스트만 보낸다. 같은 지원자 안에서 같은 값은 세션·문서를 가로질러 항상 같은 토큰(`[지원자]`, `[학교-1]`, `[회사-2]` …)이 된다. 원래 값은 `deid_mappings`에 암호화해 두며, 되돌리는 것은 `deid/reidentify.py`만 한다.

```python
config = load_deid_config(Settings().deid_file)
store = SqlTokenStore(session, FieldCipher.from_settings(), config.token_formats())
result = build_deidentifier(config, store).deidentify(text, candidate_id=cid, known=identity)
```

- 토큰 형식, 사전 파일, 켤 탐지기, 치환 예외는 `config/deid.yaml`에서 바꾼다. 토큰 형식은 아직 초안이다.
- 학교·회사 사전은 `config/deid/*.txt` (한 줄에 `정식명 | 별칭 | ...`). 사내 목록은 파일을 추가하고 `deid.yaml`에 나열한다.
- 한국어 NER은 `deid/detectors/ner.py`의 `EntityRecognizer`를 구현해 붙인다. 지금은 모델 없이 규칙 기반이다.
- 누출 검수 (합성 샘플 20건, 네트워크 없이 실행):

```bash
uv run python scripts/check_leaks.py
```

실제 샘플로 검수할 때는 같은 형식의 YAML을 만들어 `--samples`로 넘긴다. 리포트는 값을 가려서 출력한다 (`--show-values`로 해제).

## 진행 순서

[docs/implementation-order.md](docs/implementation-order.md) 참조. 현재 2단계(비식별화) 구현 완료, 사용자 확인(토큰 형식, 사전, 실제 샘플 수동 검수) 대기. 다음은 3단계 실제 LLM Provider.
