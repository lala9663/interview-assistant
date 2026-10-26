# 설치와 실행

## 백엔드

Python 3.12, [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra whisper   # 로컬 Whisper STT까지. 빼면 관리자 화면에 "패키지 없음"으로 보인다
cp .env.example .env
```

`uv sync`는 목록에 없는 패키지를 지우므로, Whisper를 쓰려면 매번 `--extra whisper`를 붙인다(`uv run`은 지우지 않는다).

### .env

| 변수 | 설명 |
| --- | --- |
| `IA_ENCRYPTION_KEY` | 지원자 신원과 비식별 역매핑을 암호화하는 Fernet 키. 없으면 업로드·답변·메모처럼 비식별화가 필요한 쓰기가 503으로 거부된다. 잃어버리면 저장된 신원을 되돌릴 수 없다. 커밋하지 않는다 |
| `IA_PROVIDERS_FILE` | 처음 기동할 때 역할별 provider 기본값. GCP 자격증명이 없으면 `config/providers.fake.yaml`(모든 AI가 fake로 돈다). 그 뒤로는 관리자 화면의 설정(DB)이 이긴다 |
| `IA_DATABASE_URL` | 기본 `sqlite+pysqlite:///./dev.db` |
| `IA_DEV_INTERVIEWER` | 로그인 전까지 로그인한 면접관의 사번. 시드의 김서연 = `E24017`(관리자) |
| `IA_UPLOADS_DIR`, `IA_RECORDINGS_DIR` | 원본 영역(업로드 서류, 녹음). git 제외, 서빙하지 않는다 |
| `IA_WEIGHTS_DIR` | 내려받은 모델 가중치(로컬 Whisper). 기본 `weights/`, git 제외 |
| `IA_DEMO_SPEED` | 가상 지원자 속도. 1이면 프론트 모의 모드와 비슷, 0이면 지연 없음 |
| `HF_ENDPOINT`, `HF_TOKEN` | 모델 다운로드에 미러나 토큰이 필요할 때만 |

암호화 키 만들기:

```bash
uv run python -c "from interview_assistant.crypto import FieldCipher as F; print(F.generate_key())"
```

### DB, 시드, 서버

```bash
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset
uv run uvicorn interview_assistant.main:app --reload
```

- 시드는 프론트 모의 데이터와 같은 가상 데이터(공고 3, 지원자 20, 면접관 5, 진행 중 면접 1, 오늘 일정, 완료 4 중 1건은 AI 채점 중)를 지금 시각 기준으로 깐다. 다른 날 다시 쓰려면 `--reset`으로 다시 넣는다. 지원자 신원도 지어낸 값(010-0000-xxxx, example.com)을 실제처럼 암호화해 넣는다. `--reset`은 모델 설정과 그 이력은 지우지 않는다.
- 로그인(SSO)은 아직 없다. Alembic 0004 이전에 시드한 DB는 관리자가 없으니 `uv run python scripts/grant_admin.py E24017`로 준다.
- 서버는 한 프로세스로 띄운다. 실시간 전사 상태와 활성 모델 설정이 메모리에 있어서 `--workers`를 쓰지 않는다.
- API 문서: http://localhost:8000/docs, 계약: [api-contract.md](api-contract.md).

### 마이그레이션 만들기

모델은 `src/interview_assistant/models/`, 마이그레이션은 `migrations/versions/`. 컬럼 타입은 SQLite, PostgreSQL, MySQL 공통 범위만 쓴다.

```bash
uv run alembic revision --autogenerate -m "describe change"
```

`tests/test_migrations.py`가 마이그레이션 결과와 모델이 일치하는지 검사한다. SQLite batch 마이그레이션은 외래 키를 끈 채로 돌고 끝나면 `PRAGMA foreign_key_check`로 확인한다(`migrations/env.py`).

## 프론트엔드

Node 24 이상. 자세한 내용은 [frontend.md](frontend.md).

```bash
cd frontend
npm ci
npm run dev          # 모의 API 모드 (백엔드 불필요) → http://localhost:5173
npm run dev:api      # 백엔드 연결 모드 (localhost:8000으로 프록시) → http://localhost:5173
```

## 테스트

```bash
uv run pytest              # 백엔드. 외부 네트워크 없이 돈다 (fake provider, 임시 SQLite 사본)
cd frontend && npm run check   # 타입 검사 + 린트 + 테스트 + 빌드
```

`tests/test_whisper.py`는 faster-whisper와 내려받은 모델 파일이 있을 때만 돌고, 없으면 건너뛴다.
