# AI 모델 설정 (관리자)

LLM, STT, 임베딩, 화자분리는 관리자 화면에서 고르고, 테스트하고, 서버 재시작 없이 바꾼다. API는 [api-contract.md](api-contract.md) "관리자 > 모델 설정", 고를 때의 기준은 [model-selection.md](model-selection.md), Whisper 측정은 [whisper-benchmark.md](whisper-benchmark.md).

## 화면

사이드바 "관리자 > 모델 설정"(또는 Ctrl+K에서 "모델"). 관리자만 보이고, API(`/api/admin/models/*`)도 관리자가 아니면 403이다. 관리자는 `Interviewer.is_admin`이며, SSO가 붙으면 그룹으로 채운다.

- **역할 6개 카드**: LLM 주 모델, LLM 선별용, STT 실시간, STT 사후, 임베딩, 화자분리. 현재 provider와 실제 모델 이름, 사용 가능 여부(안 되면 이유), 데이터 위치 배지(이 PC / 사내 GCP / 외부), 마지막 변경(누가·언제·사유).
- **변경**: provider 선택 → 모델·옵션 → 요구 조건 확인 → (외부 전송 경고) → 연결 테스트 → 사유 → 적용.
  - 요구 조건은 네트워크 없이 본다: 구현 여부, 패키지, 환경변수·자격증명 파일이 있는지(값은 보지 않음), 모델 파일.
  - API 키·자격증명은 화면에서 받지 않는다. 서버 환경변수나 Secret Manager로 넣는다.
  - 회사 밖으로 데이터를 보내는 provider는 경고를 확인해야 테스트되고, 사유까지 적어야 적용된다.
- **적용**은 재시작 없이 바로 된다. 진행 중인 면접은 시작할 때의 모델을 끝까지(실시간 전사, 꼬리질문, 종료 뒤 AI 채점까지) 쓰고, 새 면접부터 새 설정을 쓴다. 결과에는 실제 쓴 모델 이름이 남는다.
- **변경 이력**에서 이전 설정으로 되돌린다. 활성 설정과 이력은 DB(`ai_model_settings`, `ai_model_changes`, Alembic 0004)에 있고, YAML(`IA_PROVIDERS_FILE`)은 처음 기동할 때의 기본값으로만 쓴다.
- 모든 테스트·변경·다운로드는 감사 로그에 남는다. 테스트는 결과 수치만 남고, 전사나 응답 본문은 남지 않는다.

## 연결 테스트

| 역할 | 테스트 |
| --- | --- |
| LLM | 지원자 데이터가 없는 고정 문장으로 구조화 출력(JSON)과 간단한 지시 수행을 본다 |
| STT | 내장 샘플(FLEURS 한국어 11.5초, 정답과 비교한 글자 오류율), 마이크 녹음(5~10초), 파일(60초·10MB 이하). 역할의 실제 경로로 돈다(실시간 = 스트리밍, 사후 = 파일 전사). 올린 음성은 테스트가 끝나면 지운다 |
| 임베딩 | 짧은 문장 두 개의 벡터 차원 |
| 화자분리 | 샘플의 화자 구간 수 |

마이크는 Chrome·Edge에서 http://localhost:5173 을 열고 마이크 권한을 허용해야 한다. Claude 앱 안의 브라우저 창은 마이크를 막는다.

## 로컬 Whisper STT (`faster_whisper`)

OpenAI Whisper를 이 PC의 CPU에서 돌린다(faster-whisper, CTranslate2 int8, MIT). 한국어 고정, 내장 Silero VAD로 발화를 나누고, 실시간(부분·확정 전사)과 사후(파일 전사) 둘 다 된다. 음성은 PC 밖으로 나가지 않는다.

1. `uv sync --extra whisper`
2. 모델 설정 > STT 사후(또는 실시간) > 변경 > "Whisper (로컬)" > 모델 크기 카드의 "다운로드". small 486MB, medium 1.5GB, large-v3 3.1GB, large-v3-turbo 1.6GB. Hugging Face에서 커밋 고정·sha256 검증으로 받아 `weights/`(git 제외, `IA_WEIGHTS_DIR`)에 둔다. 끊겨도 이어받는다. 미러는 `HF_ENDPOINT`.
3. "기술 용어 힌트"에 자주 나오는 용어를 적는다(예: 반도체 공정, CMP, 식각, 수율). 30초 창마다 프롬프트로 들어간다.
4. 연결 테스트, 사유, 적용. 되돌리려면 변경 이력의 "되돌리기".

측정 요약(이 노트북, GPU 없음): 정확도는 medium 이상이 충분하고 small은 한국어에서 눈에 띄게 틀린다. Whisper는 호출마다 30초 창을 통째로 인코딩해 짧은 발화도 같은 비용이 들어, 이 CPU로는 실시간 전사가 발화 끝 뒤 수 초~십여 초 늦다. 화면의 권장(실시간 medium, 사후 large-v3)은 정확도 기준이다.

지금 실시간 면접 화면의 음성은 가상 지원자 대본(텍스트)이라 fake STT만 받아 적는다. STT 실시간을 Whisper로 바꾸면 새로 시작하는 면접은 수기 답변 입력으로 바뀐다(감사 로그 `transcript.unsupported_audio`). 마이크·WebRTC 입력(`live/audio.AudioSource`가 16kHz PCM을 내는 구현)이 붙으면 같은 설정이 그대로 쓰인다.

측정 다시 하기 (정답 전사가 있는 WAV 목록 JSON):

```bash
uv run python scripts/bench_whisper.py --manifest clips.json --sizes small medium large-v3-turbo large-v3
```

## provider 추가하기

1. `providers/base.py`의 인터페이스를 구현한다(`model` 이름, 필요하면 `warm_up`에서 가중치 로드).
2. `providers/registry.py`에 impl 이름을 등록한다.
3. `providers/catalog.py`에 역할, 데이터 위치, 옵션 스키마, 요구 조건(패키지·환경변수·자격증명·가중치)을 적는다.
4. 연결 테스트가 통과하면 관리자 화면에서 고를 수 있다.
