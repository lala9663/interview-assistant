# 용어집

> 다루는 것: 이 프로젝트의 코드와 문서에서 실제로 쓰는 용어의 뜻과 위치.
>
> 상태: 구현됨 · 작성 2026-10-27 · 확인: 2026-10-30

이 프로젝트의 코드와 문서에서 실제로 쓰는 표기를 모았다. 위치는 대표 하나만 적는다(코드 경로는 `src/interview_assistant/` 기준). 같은 뜻에 표기가 둘이면 문서에서 더 많이 쓰는 쪽을 앞에 둔다.

## 채용·평가

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| 역량 사전 | competency set | 직군·차수마다 평가할 역량 3~6개와 각 역량의 1~5점 행동 기준. AI 초안 → 사람 검토 → 버전으로 확정한다. 세션은 시작할 때 그 차수의 확정본을 고정한다 | `competency_sets`, `ai/competency.py` |
| 행동 기준 (BARS) | Behaviorally Anchored Rating Scales | 점수마다 "어떤 행동을 보이면 몇 점"인지 적은 척도. AI 채점은 답변을 이 기준에 비추어 읽는다 | `ai/prompts.py`, `ai/scoring.py` |
| 전형 차수, 차수 | interview round | 공고마다 정한 면접 순서(1차 직무 면접, 2차 임원 면접 …, 최대 6). 차수마다 진행 방식·권장 면접관 수·이전 차수 점수 공개를 정한다 | `interview_rounds`, `interviews.py` |
| 차수 결정 | round decision | 면접관 전원이 점수를 낸 뒤 사람이 하는 합격·보류·불합격. 사유 필수, 바꾸면 새 revision이 쌓인다. 다음 차수 세션이 생기면 바꿀 수 없다 | `round_decisions` |
| 최종 합격 후보 | | 마지막 차수 합격. 공식 결과는 채용 사이트가 낸다 | `interviews.py` |
| 확인할 점 | check point | 다음 차수에서 확인할 것. 면접관이 남기거나, AI가 채점 뒤 답변을 인용해 뽑는다 | `check_points`, `ai/checkpoints.py` |
| 사전 질문 | preset question | 차수마다 미리 정한 질문 | `preset_questions` |
| 이어 질문 | carryover question | 이전 차수 답변과 확인할 점으로 이 지원자에게만 묻는 질문. 기댄 답변을 인용한다 | `preset_questions.session_id`, `ai/presets.py` |
| 꼬리질문 | follow-up question | 직전 답변을 보고 이어 묻는 질문. 질문 은행 후보가 먼저, AI 후보가 이어서 뜬다 | `ai/followups.py` |
| AI 참고 점수 | AI score | 근거 인용이 필수인 AI 점수. 3회 샘플의 중앙값. 면접관 점수와 나란히 보이고 합산하지 않는다 | `ai/scoring.py`, `scores` |
| 평점 기준 예시, 기준점 | rubric example, anchor | 역량별 1~5점 수준을 보여 주는 가상 답변. 채점 프롬프트 `<anchors>`에 넣는다. 답변과의 유사도로 점수를 매기지 않는다 | `rubric_examples`, `retrieval/bank.py`의 `anchors_for` |
| 이전 차수 점수 공개 | show previous scores | N차 화면에 이전 차수 점수를 보일지. 기본 꺼짐(기준점 효과를 피하려고) | `interview_rounds.show_previous_scores` |
| 서류 선별 | screening | 비식별 서류로 프로필을 만들고 JD·역량 기준 적합도와 근거를 낸다. 통과·탈락은 사람이 정한다 | `ai/screening.py`, `screenings` |
| 가명 | pseudonym | 화면에 보이는 지원자 이름 대신 쓰는 번호(CAND-0021 …) | `candidates.pseudonym` |
| FR-01~09 | functional requirement | 업무정의서의 요구사항 번호 | [README.md](../../README.md) "9개 요구사항과 상태" |

## 비식별화·보안

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| 비식별화 | de-identification | 이름·연락처·학교·회사 등을 토큰으로 바꾸는 일. LLM과 화면에는 비식별 텍스트만 간다 | `deid/deidentifier.py`, [deidentification.md](../deidentification.md) |
| 비식별화 토큰 | token | `[지원자]`, `[학교-1]`, `[전화-2]` 같은 자리 표시. 같은 지원자 안에서 같은 값은 세션·문서를 넘어 늘 같은 토큰이 된다. 형식은 아직 초안 | `config/deid.yaml`, `deid/store.py` |
| 역매핑 (역방향 맵) | reverse mapping | 토큰 → 원래 값. 암호화해 저장하고, 되돌리는 곳은 하나뿐이며 호출마다 감사 로그를 남긴다 | `deid_mappings`, `deid/reidentify.py` |
| 탐지기 | detector | 비식별화에서 값을 찾는 규칙 묶음: 본인 정보, 정규식, 사전, 형태 패턴, 호칭 붙은 이름, NER 자리, OCR 오독 | `deid/detectors/` |
| 누출, 근접 누출 | leak, near leak | 비식별 결과에 정답 값이 남은 것. 근접 누출은 OCR이 잘못 읽은 채 남은 것(자모 근사, 숫자 하나 차이) | `deid/leaks.py`, `scripts/check_leaks.py` |
| 숨은 텍스트 | hidden block | 흰 글씨, 0.5pt 글자, 슬라이드 밖 도형처럼 보이지 않는 텍스트. 비식별화는 하고 선별 프롬프트에서는 뺀다 | `documents/types.py` |
| 원본 영역 | | 식별 정보가 든 원문을 두는 곳: 업로드 원본, 녹음, 원문 답변(`QAItem.answer_text`), 검토 리포트. 화면·LLM으로 나가지 않고 git에서 빠진다 | `uploads/`, `recordings/`, `reports/` |
| 가드 | guard | LLM 호출 직전에 지원자 텍스트에 그 지원자의 이름·연락처·학교·회사, 전화·이메일·주민번호 모양이 남았는지 다시 보고, 남았으면 호출하지 않는다 | `ai/guard.py` |
| AI 게이트웨이 | gateway | 모든 LLM 호출이 지나는 길: 가드 → provider → 감사 로그 | `ai/gateway.py` |
| 감사 로그 | audit log | 모든 AI 호출과 주요 행동 기록. 모델, 프롬프트 버전, 토큰 수는 남기고 프롬프트·응답 본문은 남기지 않는다 | `audit_logs`, `models/audit.py` |
| 컬럼 암호화 | field encryption | 신원·역매핑 등 민감 컬럼을 Fernet으로 암호화 | `crypto.py`, `IA_ENCRYPTION_KEY` |
| 데이터 위치 배지 | data location | 관리자 화면에서 provider마다 보이는 배지: 이 PC / 설정한 사내 서버 / 외부 클라우드 (Google) / 외부. 회사 밖으로 나가는 "외부 클라우드 (Google)"와 "외부"는 경고 확인과 사유가 있어야 적용된다. 2026-10-28 전에는 Google 계열을 "사내 GCP"로 불렀다 | `providers/catalog.py`의 `DataLocation` |
| 녹음 동의, 수기 모드 | consent, manual mode | 녹음은 동의가 있을 때만 한다. 동의가 없거나 STT가 죽으면 면접관이 답변을 손으로 적는다 | [api-contract.md](../api-contract.md) 3.1 |

## AI·검색

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| provider | provider | LLM·STT·임베딩·화자분리·OCR·VAD·답변 끝 판정의 구현 하나. 인터페이스 뒤에 두고 관리자 화면에서 바꿔 낀다 | `providers/base.py`, `providers/registry.py` |
| 역할 | role | provider를 쓰는 자리: `llm.primary`, `llm.screening`, `stt.streaming`(실시간), `stt.batch`(사후), `embedding`, `diarization`, 서류 읽기 다섯(`document.*`), 음성 입력 셋(`audio.vad`, `audio.turn`, `audio.denoise`). 모두 14개 | `providers/catalog.py`, [ai-models.md](../ai-models.md) |
| 카탈로그 | catalog | 관리자 화면이 고르는 목록: 역할, 데이터 위치, 옵션, 요구 조건(네트워크 없이 확인) | `providers/catalog.py` |
| fake provider | fake provider | 자격증명 없이 도는 구현. 흐름과 화면 확인용이고 내용의 품질은 없다 | `providers/fake.py`, `config/providers.fake.yaml` |
| revision 고정 | pinning | 모델 설정을 바꿀 때마다 전역 revision이 오른다. 면접 세션은 시작할 때의 revision(`ai_config_revision`)에 고정되어 실시간 전사·꼬리질문·채점까지 그 provider로 끝난다. 서류 처리도 시작할 때의 스냅샷 하나로 끝난다 | `ai_models/manager.py`, `runtime.py`의 `pinned` |
| 연결 테스트 | probe | 적용 전에 고정 문장·내장 샘플로 provider를 시험 | `ai_models/probe.py` |
| 워밍업 | warm-up | 적용할 때 모델 가중치를 미리 올려 면접 중에 로딩 시간이 들지 않게 한다 | `providers/base.py`의 `warm_up` |
| 가중치 고정 다운로드 | pinned weights | 모델 파일을 관리자가 누를 때만, 커밋 고정·sha256 검증·이어받기로 받는다 | `providers/weights.py`, `weights/` |
| 질문 은행 | question bank | 직군·역량·차수별로 채용 담당자가 검수한 질문과 좋은 꼬리질문 예시. 초안 → 승인 → 폐기. 승인된 것만 검색된다 | `question_bank_items`, [question-bank.md](../question-bank.md) |
| 금지 질문 | prohibited question | 가족·출신지·혼인·종교·나이 등 직무와 무관해 물으면 안 되는 질문. 12범주 규칙과 AI로 경고한다(막지는 않음) | `ai/question_rules.py` |
| few-shot 예시 | few-shot examples | 프롬프트에 넣는 좋은 질문 예시. 꼬리질문 프롬프트의 `<example_questions>`에 가까운 승인 질문 4개 | `ai/prompts.py` |
| 임베딩 | embedding | 텍스트를 숫자 벡터로 바꾼 것. 회사가 쓴 텍스트만 저장하고, 지원자 답변은 검색할 때 메모리에서만 쓴다 | `retrieval/`, `embedding_vectors` |
| 밀집 벡터 | dense vector | 뜻을 담은 벡터. BGE-M3는 1024차원 | `providers/embedding/bge_m3.py` |
| 희소 가중치 (단어 일치) | sparse / lexical weights | 토큰마다 붙는 가중치. 약어·전문 용어가 그대로 겹칠 때 점수를 올린다 | 같은 파일 |
| 하이브리드 점수 | hybrid score | 의미 유사도 + `sparse_weight`(0.3) × 단어 일치 | `retrieval/index.py`, [embedding-benchmark.md](../embedding-benchmark.md) |
| hit@k (상위 k개 적중) | hit@k | 정답이 검색 결과 상위 k개 안에 든 비율. 이 저장소의 한국어 평가 세트 hit@3 94.6% | `scripts/eval_retrieval.py` |
| MRR | mean reciprocal rank | 정답 순위의 역수 평균 | 같은 파일 |
| 색인, 재색인 | index, reindex | 임베딩 모델(`index_key` = 모델@커밋/차원)마다 벡터 묶음 하나. 모델을 바꾸면 백그라운드로 새로 만들고, 끝날 때까지 이전 색인으로 검색한다 | `retrieval/service.py`, `embedding_indexes` |
| 같은 질문으로 볼 유사도 (중복 임계값) | `duplicate_threshold` | 이 값 이상이면 같은 뜻의 질문으로 보고 후보에서 뺀다. BGE-M3 0.85 | `retrieval/bank.py`의 `duplicate_of` |
| 질문 은행 제안 최소 점수 | `min_score` | 이보다 약한 질문 은행 후보는 보이지 않는다. BGE-M3 0.55 | `providers/catalog.py` |
| 출처 배지, 채택률 | source, adoption rate | 꼬리질문 후보가 질문 은행에서 왔는지 AI에서 왔는지, 출처별로 면접관이 고른 비율 | 관리자 > 꼬리질문 지표 |

## 음성

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| STT 실시간 / STT 사후 | streaming / batch STT | 면접 중 바로 받아 적는 역할(속도 우선)과, 끝난 뒤 녹음 전체로 다시 받아 적는 역할(정확도 우선) | `stt.streaming`, `stt.batch`, [model-selection.md](../model-selection.md) 1장 |
| 부분 전사 / 확정 전사 | partial / final | 말하는 도중 계속 바뀌는 전사와 그 구간이 끝나 확정된 전사. 확정만 저장한다 | SSE `segment.partial`·`segment.final` |
| CER / WER | character / word error rate | 글자(단어) 편집 거리 ÷ 정답 글자(단어) 수. 이 저장소는 공백·문장부호를 빼고 센 CER을 쓴다 | [whisper-benchmark.md](../whisper-benchmark.md) |
| 실시간 대비 | RTFx | 이 저장소의 정의는 음성 길이 ÷ 처리 시간(1보다 크면 말보다 빠름). Open ASR Leaderboard의 RTFx와 같고, 흔히 쓰는 RTF(처리 시간 ÷ 음성 길이)와는 방향이 반대다 | [whisper-benchmark.md](../whisper-benchmark.md) |
| 30초 창 | 30-second window | Whisper 인코더가 호출마다 30초를 통째로 인코딩하는 것. 짧은 발화도 비용이 같아 CPU 실시간이 느린 이유 | `providers/stt/faster_whisper.py` |
| 16kHz 모노 PCM16 | `PCM16_16K` | STT에 넣는 오디오 형식(16비트, 초당 16,000샘플, 한 채널) | `providers/base.py` |
| 오디오 소스 | `AudioSource` | 전사 허브에 소리를 넣는 입력. 대본을 읽는 가상 지원자(`live/audio.py`)와 브라우저 마이크(`MicrophoneSource`, 16kHz PCM). WebRTC 트랙은 아직 없다 | `live/audio.py`, `live/microphone.py` |
| VAD | voice activity detection | 소리 중 사람 말이 있는 구간을 찾는 것. faster-whisper에 든 Silero VAD를 쓴다. 마이크 경로는 VAD로 말소리만 STT에 넣는다 | `audio.vad` 역할, Whisper의 `vad_min_silence_ms` 옵션 |
| 발화 끝 | end of utterance | VAD가 일정 시간(기본 500ms) 침묵을 보면 그 발화를 끝으로 보고 확정 전사를 낸다 | 같은 옵션 |
| 답변 끝 판단, 답변 닫힘 | end-of-turn detection | 지원자가 답변을 다 했다고 보고 그 Q&A의 답변을 닫는 것(`qa.answered`). 닫히면 꼬리질문을 요청한다. 기본은 Smart Turn v3(말이 1초 멈추면 판정, 기준 0.8, 모델 파일이 없으면 침묵 2초) | `audio.turn` 역할, [audio-input.md](../audio-input.md) 5장 |
| 기술 용어 힌트 | initial prompt, phrase hint | 자주 나오는 용어를 STT에 미리 알려 그 표기로 받아 적게 하는 것 | `initial_prompt` 옵션 |
| AEC / NS / AGC | acoustic echo cancellation / noise suppression / automatic gain control | 에코 제거, 잡음 억제, 자동 음량. 브라우저 마이크 옵션으로 켠다 | [audio-quality.md](audio-quality.md) |
| 화자분리 | speaker diarization | 녹음에서 "누가 언제 말했나"를 화자1·화자2로 나누는 것. 그 화자가 누구인지는 따로 잇는다 | `diarization` 역할, [diarization.md](diarization.md) |
| DER | diarization error rate | 화자분리 오류율: (놓친 말 + 없는 말을 말로 본 것 + 화자 혼동) ÷ 전체 말 시간 | [diarization.md](diarization.md) |
| 환각 | hallucination | STT가 침묵·잡음 구간에서 하지 않은 말을 지어내는 것 | [audio-quality.md](audio-quality.md) |

## 서류 읽기

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| 텍스트 층 | text layer | PDF 등에 글자 코드로 들어 있는 텍스트. 스캔본에는 없다 | `documents/reading.py` |
| OCR | optical character recognition | 그림 속 글자를 읽는 것. 이 프로젝트는 원본 영역 안에서만 하고 그림은 모델로 보내지 않는다 | `providers/ocr/` |
| 읽기 방식 | reading mode | 자동(텍스트 우선, 없거나 깨지면 OCR) / 항상 OCR / 텍스트만 | `documents/reading.py`의 `PageReader.plan` |
| 깨짐 판정 | garbled text detection | 화면엔 한글인데 엉뚱한 코드로 읽히는 텍스트 층을 찾아 OCR로 다시 읽는 규칙. 민감도 낮음·보통·높음 | `documents/quality.py` |
| 보류 | needs OCR | 읽지 못한 쪽이 있어 문서 전체를 처리하지 않은 상태(`ocr_required`, `ocr_unavailable`) | [document-reading.md](../document-reading.md) |
| 증명사진 판정 | ID photo detection | 모양·색 분포로 증명사진을 골라 읽지 않고 버린다 | `documents/images.py` |
| 비슷한 글자 고치기 | OCR confusables fix | 숫자 덩어리 안의 O·l·I를 숫자로 바꾸는 등 OCR 오독 보정 | `documents/ocrfix.py` |
| 신뢰도 경고 기준 | confidence threshold | OCR 신뢰도가 이보다 낮은 쪽은 경고로 남긴다(기본 0.8) | 읽기 방식 옵션 |
| 작업 프로세스 | isolated worker process | PaddleOCR을 서버와 다른 프로세스에서 돌리는 것(Whisper와 DLL 충돌을 피하려고) | `providers/isolated.py` |

## 연동·개발

| 용어 | 영어 | 뜻 | 위치 |
| --- | --- | --- | --- |
| 채용 사이트 연동 (수신) | site intake | 채용 사이트가 보낸 지원서 이벤트(제출·수정·철회)를 받아 처리 | `intake/`, [site-intake-spec.md](../site-intake-spec.md) |
| 처리 함수 하나 | `process_application` | 업로드·사이트 등 어느 통로로 와도 같은 함수가 처리한다 | `intake/service.py` |
| HMAC 서명 | HMAC-SHA256 signature | 보낸 쪽이 공유 키로 시각·메서드·경로·본문 해시에 서명. 300초 창 밖 요청은 거절 | `intake/signature.py`, 명세 4장 |
| 멱등 | idempotency | 같은 이벤트를 여러 번 받아도 한 번만 반영. `event_id`와 내용 지문으로 본다 | `intake/events.py`, `intake_events`, 명세 5장 |
| 받지 않는 항목 | forbidden items | 가족·신체·출신지·혼인 등 받으면 안 되는 칸. 오면 422로 거절 | 명세 6장 |
| 대조 | reconcile | 놓친 이벤트를 사이트와 맞춰 보는 절차. 명세만 있고 구현 안 함 | 명세 9.2 |
| SSE | server-sent events | 서버 → 브라우저 한 방향 스트림. 실시간 전사와 꼬리질문에 쓴다. WebSocket은 마이크 음성을 올리는 데만 쓴다 | [api-contract.md](../api-contract.md) 3장, `frontend/src/api/sse.ts` |
| 모의 API | mock API (MSW) | 백엔드 없이 브라우저가 `/api`에 답하는 모드(`npm run dev`). `npm run dev:api`는 실제 백엔드 | `frontend/src/mocks/`, [frontend.md](../frontend.md) |
| extra | optional dependencies | `uv sync --extra whisper --extra ocr --extra embedding --extra agent`. extra 없이 `uv sync`를 돌리면 이 패키지들이 지워진다 | `pyproject.toml`, [setup.md](../setup.md) |
| 시드 | seed | 데모 데이터를 DB에 넣는 것 | `scripts/seed_demo.py` |
| N단계 | step N | 구현 순서의 0~12단계(10 STT 배치, 11 비대면 실시간, 12 평가셋·게이트 1) | [implementation-order.md](../implementation-order.md) |
| 게이트 1 | gate 1 | 12단계의 통과 기준 4개: 면접관 점수 일치도, 비식별 누출률, 1건당 비용, 모델 교체 검증 | 같은 문서 |
