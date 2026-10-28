# 설치와 실행

## 백엔드

Python 3.12, [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra whisper --extra ocr --extra embedding   # 로컬 Whisper STT, 로컬 OCR(PaddleOCR), 로컬 임베딩(BGE-M3)까지. 빼면 관리자 화면에 "패키지 없음"으로 보인다
cp .env.example .env
```

`uv sync`는 목록에 없는 패키지를 지우므로, 매번 같은 `--extra`를 붙인다(`uv run`은 지우지 않는다). 에이전트용 MCP 서버(`python -m interview_assistant.agent`, [agent-integration.md](agent-integration.md))는 `--extra agent`로 받는다. 개발 환경에는 dev 그룹에도 같은 `mcp`가 있어 테스트가 늘 돈다. `ocr`은 paddleocr 3.7.0과 paddlepaddle 3.2.2(CPU, 약 500MB)다. `embedding`은 onnxruntime과 tokenizers로, faster-whisper가 이미 쓰는 패키지라 따로 받는 것은 거의 없다.

### 시스템 프로그램 (선택)

서류 읽기의 일부는 파이썬 밖 프로그램을 부른다. 없으면 그 기능만 관리자 화면에 "프로그램 없음"으로 보이고 나머지는 돈다.

| 프로그램 | 쓰는 곳 | Windows | Ubuntu | 다른 위치 |
| --- | --- | --- | --- | --- |
| LibreOffice | 구형 .doc·.ppt 변환. 없으면 그런 서류는 "변환기 없음"으로 거부 | `winget install TheDocumentFoundation.LibreOffice` | `apt install libreoffice-core libreoffice-writer libreoffice-impress` | `SOFFICE_CMD` |
| Tesseract | OCR 엔진 Tesseract(비교용, 기본은 PaddleOCR) | `winget install UB-Mannheim.TesseractOCR` | `apt install tesseract-ocr` | `TESSERACT_CMD` |

OCR 모델 파일(PaddleOCR PP-OCRv5, Tesseract 한국어 데이터)과 임베딩 모델(BGE-M3, 약 2.3GB)은 설치가 아니라 관리자 > 모델 설정의 "다운로드"로 받는다([ai-models.md](ai-models.md) "서류 읽기", "로컬 임베딩 BGE-M3").

### .env

| 변수 | 설명 |
| --- | --- |
| `IA_ENCRYPTION_KEY` | 지원자 신원과 비식별 역매핑을 암호화하는 Fernet 키. 없으면 업로드·답변·메모처럼 비식별화가 필요한 쓰기가 503으로 거부된다. 잃어버리면 저장된 신원을 되돌릴 수 없다. 커밋하지 않는다 |
| `IA_PROVIDERS_FILE` | 처음 기동할 때 역할별 provider 기본값. 실제 모델(사내 모델 서버, 내려받은 로컬 모델 파일)이 준비되지 않았으면 `config/providers.fake.yaml`(모든 AI가 fake로 돈다). 그 뒤로는 관리자 화면의 설정(DB)이 이긴다 |
| `IA_DATABASE_URL` | 기본 `sqlite+pysqlite:///./dev.db` |
| `IA_DEV_INTERVIEWER` | 로그인 전까지 로그인한 면접관의 사번. 시드의 김서연 = `E24017`(관리자) |
| `IA_UPLOADS_DIR`, `IA_RECORDINGS_DIR` | 원본 영역(업로드 서류, 녹음). git 제외, 서빙하지 않는다 |
| `IA_WEIGHTS_DIR` | 내려받은 모델 가중치(로컬 Whisper, PaddleOCR, Tesseract 한국어 데이터, BGE-M3). 기본 `weights/`, git 제외 |
| `SOFFICE_CMD`, `TESSERACT_CMD` | LibreOffice·Tesseract 실행 파일 경로. PATH와 기본 설치 위치에 없을 때만 |
| `IA_DEMO_SPEED` | 가상 지원자 속도. 1이면 프론트 모의 모드와 비슷, 0이면 지연 없음 |
| `IA_SITE_SECRET`, `IA_SITE_SECRET_PREVIOUS` | 채용 사이트 연동의 공유 HMAC 키([site-intake-spec.md](site-intake-spec.md) 4장). 없으면 사이트 수신 엔드포인트가 503. 키 교체 중에는 이전 키도 받는다. 커밋하지 않는다 |
| `IA_SITE_CLOCK_SKEW` | 서명 시각 허용 차이(초, 기본 300) |
| `IA_INTAKE_WORKERS` | 받은 지원서 이벤트를 처리하는 백그라운드 워커 수(기본 4, 0이면 큐에 쌓이기만 한다) |
| `IA_AGENT_IDENTITY`, `IA_AGENT_TOKEN_SECRET` | 에이전트(MCP) 호출의 신원 확인 방식(지금은 `dev_token`뿐)과 개발용 토큰 서명 키. 키가 없으면 에이전트 호출이 503. 토큰은 `uv run python scripts/agent_token.py <사번>`. 플랫폼·SSO의 신원 확인을 더하면 바꾼다([agent-integration.md](agent-integration.md) 7장). 커밋하지 않는다 |
| `IA_MCP_API_URL`, `IA_MCP_WEB_URL`, `IA_MCP_AGENT_NAME`, `IA_MCP_IDENTITY_HEADERS`, `IA_MCP_TOKEN` | MCP 서버(`python -m interview_assistant.agent`)만 읽는다. API 주소, 링크의 웹 주소, 감사 로그의 에이전트 이름, HTTP에서 사용자 토큰을 실어 오는 헤더, stdio로 쓸 때 그 사람의 토큰. `agent` extra 필요 |
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

- 시드에는 질문 은행 40개(승인 37, 금지 질문 경고가 붙은 초안 1, 초안 1, 폐기 1)와 평점 기준 예시 16개도 들어간다. 그 벡터는 시드하지 않고 서버가 기동할 때 활성 임베딩 모델로 만든다(fake면 수 초, BGE-M3면 약 15초).
- 시드는 프론트 모의 데이터와 같은 가상 데이터(공고 3, 지원자 20, 면접관 5, 진행 중 면접 1, 오늘 일정, 완료 4 중 1건은 AI 채점 중)를 지금 시각 기준으로 깐다. 다른 날 다시 쓰려면 `--reset`으로 다시 넣는다. 지원자 신원도 지어낸 값(010-0000-xxxx, example.com)을 실제처럼 암호화해 넣는다. `--reset`은 모델 설정과 그 이력은 지우지 않는다.
- 로그인(SSO)은 아직 없다. Alembic 0004 이전에 시드한 DB는 관리자가 없으니 `uv run python scripts/grant_admin.py E24017`로 준다.
- 서버는 한 프로세스로 띄운다. 실시간 전사 상태, 활성 모델 설정, 지원서 수신 큐의 워커가 메모리에 있어서 `--workers`를 쓰지 않는다. OCR 엔진을 PaddleOCR로 쓰면 서버가 작업 프로세스를 하나 더 띄운다(읽는 동안 최대 약 1.8GB, 쉴 때 0.6GB 안팎. faster-whisper와 DLL이 충돌해 따로 돈다, [document-reading.md](document-reading.md)).
- API 문서: http://localhost:8000/docs, 계약: [api-contract.md](api-contract.md).

### 가짜 채용 사이트로 연동 확인

`.env`에 `IA_SITE_SECRET`을 넣고 서버를 띄운 뒤, 같은 키로 가짜 채용 사이트가 서명된 지원서 이벤트를 보낸다(키는 `--secret`, 환경변수, `.env` 순으로 읽는다). 시드는 공고 P1·P2를 `DS-2026-0101`·`DS-2026-0102`에 연결하고 P3(`DS-2026-0103`)은 비워 두므로, P3 이벤트는 연동 현황에서 "모르는 공고 번호"로 실패했다가 공고 화면에서 번호를 연결하고 "다시 처리"하면 들어온다.

```bash
uv run python scripts/fake_recruiting_site.py --url http://127.0.0.1:8000 --count 500
uv run python scripts/fake_recruiting_site.py --url http://127.0.0.1:8000 --count 500   # 같은 날 다시: 전부 중복으로 응답, 새로 반영 없음
```

Windows에서는 `localhost` 대신 `127.0.0.1`을 쓴다(`localhost`는 IPv6를 먼저 시도해 요청마다 약 2초 늦어진다). 화면은 관리자 > 연동 현황(`/admin/intake`)과 서류 선별의 "경로" 열.

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

`tests/test_whisper.py`는 faster-whisper와 내려받은 모델 파일이 있을 때만, `tests/test_bge_m3.py`는 BGE-M3 모델 파일이 있을 때만, `tests/test_ocr_engines.py`는 PaddleOCR·Tesseract와 모델 파일이 있을 때만, LibreOffice가 필요한 구형 .doc·.ppt 테스트는 LibreOffice가 있을 때만 돌고 없으면 건너뛴다. 나머지는 fake OCR로 오프라인에서 돈다.
