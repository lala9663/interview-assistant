# AI 모델 설정 (관리자)

LLM, STT, 임베딩, 화자분리와 서류 읽기 도구(OCR 엔진 등)는 관리자 화면에서 고르고, 테스트하고, 서버 재시작 없이 바꾼다. API는 [api-contract.md](api-contract.md) "관리자 > 모델 설정", 고를 때의 기준은 [model-selection.md](model-selection.md), 사내에 올릴 오픈 웨이트 LLM 비교는 [reference/llm.md](reference/llm.md), 측정은 [whisper-benchmark.md](whisper-benchmark.md)와 [ocr-benchmark.md](ocr-benchmark.md), 서류 읽기 규칙은 [document-reading.md](document-reading.md).

## 화면

사이드바 "관리자 > 모델 설정"(또는 Ctrl+K에서 "모델"). 관리자만 보이고, API(`/api/admin/models/*`)도 관리자가 아니면 403이다. 관리자는 `Interviewer.is_admin`이며, SSO가 붙으면 그룹으로 채운다.

- **역할 카드 11개, 두 묶음**: AI 모델(LLM 주 모델, LLM 선별용, STT 실시간, STT 사후, 임베딩, 화자분리, 그 아래 임베딩 색인 상태)과 서류 읽기(읽기 방식, OCR 엔진, PDF 텍스트 추출, HWP·HWPX 읽기, 구형 오피스 변환). 현재 provider와 실제 모델 이름, 사용 가능 여부(안 되면 이유), 데이터 위치 배지(이 PC / 설정한 사내 서버 / 외부 클라우드 (Google) / 외부), 마지막 변경(누가·언제·사유).
- **변경**: provider 선택 → 모델·옵션 → 요구 조건 확인 → (외부 전송 경고) → 연결 테스트 → 사유 → 적용.
  - 요구 조건은 네트워크 없이 본다: 구현 여부, 패키지, 환경변수·자격증명 파일이 있는지(값은 보지 않음), 모델 파일.
  - API 키·자격증명은 화면에서 받지 않는다. 서버 환경변수나 Secret Manager로 넣는다.
  - 회사 밖으로 데이터를 보내는 provider(외부 API, Google Cloud)는 경고를 확인해야 테스트되고, 사유까지 적어야 적용된다. 되돌리기로 그쪽으로 돌아갈 때도 같다.
- **적용**은 재시작 없이 바로 된다. 진행 중인 면접은 시작할 때의 모델을 끝까지(실시간 전사, 꼬리질문, 종료 뒤 AI 채점까지) 쓰고, 새 면접부터 새 설정을 쓴다. 처리 중인 서류도 시작할 때의 읽기 설정으로 끝난다. 결과에는 실제 쓴 모델 이름(서류는 읽기 도구와 버전)이 남는다.
- **변경 이력**에서 이전 설정으로 되돌린다. 활성 설정과 이력은 DB(`ai_model_settings`, `ai_model_changes`, Alembic 0004)에 있고, YAML(`IA_PROVIDERS_FILE`)은 처음 기동할 때의 기본값으로만 쓴다.
- 모든 테스트·변경·다운로드는 감사 로그에 남는다. 테스트는 결과 수치만 남고, 전사나 응답 본문은 남지 않는다.

## 연결 테스트

| 역할 | 테스트 |
| --- | --- |
| LLM | 지원자 데이터가 없는 고정 문장으로 구조화 출력(JSON)과 간단한 지시 수행을 보고, 꼬리질문처럼 짧은 스트리밍을 한 번 받는다. 응답 시간, 스트리밍 첫 토큰 시간, 서버가 알려 준 모델 이름을 보여 준다. 호출 둘 다 게이트웨이(가드 + 감사 로그)를 거친다 |
| STT | 내장 샘플(FLEURS 한국어 11.5초, 정답과 비교한 글자 오류율), 마이크 녹음(5~10초), 파일(60초·10MB 이하). 역할의 실제 경로로 돈다(실시간 = 스트리밍, 사후 = 파일 전사). 올린 음성은 테스트가 끝나면 지운다 |
| 임베딩 | 지원자 데이터가 없는 고정 문장 세 개(문장, 같은 약어 FDC를 쓴 비슷한 문장, 무관한 문장)로 차원, 희소 가중치 유무, 비슷한 문장이 무관한 문장보다 가까운지. 아니면 실패 |
| 화자분리 | 샘플의 화자 구간 수 |
| 서류 읽기 | 역할별 내장 가상 이력서(OCR은 글자 그림 PNG, 읽기 방식은 텍스트+스캔 혼합 PDF, HWP는 HWPX, 구형 변환은 .doc) 또는 올린 파일(10MB). 테스트하는 설정 + 나머지 서류 읽기 역할의 활성 설정으로 읽고, 쪽마다 방법·이유·도구·신뢰도·시간, 그림마다 판단, 비식별화한 미리보기를 보여 준다. 내장 샘플은 정답과 비교한 글자 오류율도. 원문은 화면에도 감사 로그에도 없다 |

마이크는 Chrome·Edge에서 http://localhost:5173 을 열고 마이크 권한을 허용해야 한다. Claude 앱 안의 브라우저 창은 마이크를 막는다.

## 사내 오픈소스 모델 서버 LLM (`open_model_server`)

사내에 설치한 오픈 웨이트 모델 서버(vLLM, Ollama, SGLang 등)를 LLM 주 모델·선별용으로 쓴다. 이런 서버가 주는 OpenAI 형식 API(`POST /v1/chat/completions`, `GET /v1/models`)로 부르지만 OpenAI 서비스로는 보내지 않는다. openai.com과 Azure OpenAI(`*.openai.azure.com`) 주소는 화면에서도, YAML·되돌리기로 들어온 설정에서도 거부한다. 비식별 텍스트만 가고(가드가 호출 직전에 다시 본다), 프롬프트와 응답은 저장하지 않는다. 데이터 위치 배지는 "설정한 사내 서버"다. 그 주소가 정말 사내인지는 앱이 알 수 없으니 회사 밖 주소를 적지 않는다. 어떤 모델을 올릴지는 [reference/llm.md](reference/llm.md). `config/providers.yaml`의 기본 LLM이 이 provider(예시 주소)이고, YAML은 처음 기동할 때만 읽으니 실제 주소는 화면에서 바꾼다.

| 옵션 | 기본 | 설명 |
| --- | --- | --- |
| 서버 주소 `base_url` | 비움 (필수) | `/v1`까지. 예: vLLM `http://10.0.0.5:8000/v1`, Ollama `http://10.0.0.5:11434/v1`. 주소 안의 사용자 이름·비밀번호, `?`·`#`도 받지 않는다 |
| 모델 이름 `model` | 비움 (필수) | 서버에 올린 이름 그대로. vLLM은 `--served-model-name`(없으면 Hugging Face 경로), Ollama는 `gemma4:e4b`처럼 태그까지 |
| API 키 환경변수 이름 `api_key_env` | 비움 | 키가 든 환경변수의 이름(예: `IA_LLM_API_KEY`). 값은 앱 서버 환경에만 두고 화면·DB에는 이름만 남는다. 요구 조건에 그 변수가 있는지(값 아님)가 보이고, `Authorization: Bearer <값>`으로 보낸다 |
| 타임아웃 `timeout` | 120초 | 요청 하나를 기다리는 최대 시간. 스트리밍은 토큰 사이 간격. GPU 없는 서버면 늘린다 |
| 최대 출력 토큰 `max_tokens` | 4096 | 앱이 요청마다 정한 값과 이 값 중 작은 쪽. 서버의 컨텍스트 길이에서 입력 길이를 뺀 것보다 작아야 한다 |
| 온도 `temperature` | 0.3 | AI 채점이 한 답변을 세 번 채점해 중앙값을 쓰므로 0보다 조금 크게 |
| 구조화 출력 방식 `structured_output` | JSON 스키마 강제 | `json_schema`(vLLM·SGLang·Ollama가 스키마대로만 생성) / `json_object` / `prompt`(서버가 `response_format`을 거부할 때). 스키마는 어느 방식이든 프롬프트에도 넣고, 받은 답은 코드 블록·앞뒤 말·`<think>`를 걷어 JSON 객체로 읽는다 |
| 추가 헤더 `headers` | 비움 | 사내 게이트웨이용 `이름: 값` 줄. 이름에 key·token·auth·secret·cookie·password가 들어가면 값은 `${환경변수}`로만 적는다(`Bearer ${IA_GW_TOKEN}`은 된다) |
| 추가 요청 필드 `extra_body` | 비움 | 서버별 옵션 JSON 객체. `model`·`messages`·`stream`·`max_tokens`·`temperature`·`response_format`·`tools` 같은 필드는 넣을 수 없다 |

적용 전 워밍업이 `GET /models`로 서버·인증·모델 이름을 확인한다(Ollama의 `qwen3`은 `qwen3:latest`와 같게 본다. 모델 목록을 주지 않는 게이트웨이는 첫 호출에서 확인된다). 연결 테스트가 실패하면 원인을 나눠 보여 준다. 감사 로그에는 오류 종류(클래스 이름)만 남는다.

| 원인 | 예 |
| --- | --- |
| 주소 오류 | 연결 거부·연결 시간 초과, `/v1`이 빠진 경로(404), 다른 주소로 넘김(3xx), 모델 서버가 아닌 응답 |
| 인증 실패 | 401·403, 키 환경변수가 서버 환경에 없음. 서버가 받은 키를 되돌려 보내도 오류 문장에서 지운다 |
| 모델 없음 | 서버 목록에 없는 이름(서버가 가진 모델을 함께 보여 줌), vLLM·Ollama의 "model not found" |
| 시간 초과 | 타임아웃 안에 응답이 끝나지 않음, 게이트웨이의 408·504 |
| 서버 오류, 응답 형식 오류 | 5xx, 스트리밍 중 오류, JSON이 아니거나 최대 출력 토큰에서 잘린 답 |

추론(thinking) 모델(Qwen3 계열, gpt-oss 등): 서버가 추론을 따로 주는 필드(`reasoning_content`, `reasoning`)는 버리고 답 앞의 `<think>…</think>`도 빼서 꼬리질문에는 답만 보인다. 그래도 추론하는 동안 첫 토큰이 늦으니 꼬리질문에 쓰려면 서버에서 추론을 끈다.

도구 호출(tool calling)은 이번 범위 밖이다. 요청에 `tools`를 넣지 않고 `extra_body`로도 넣을 수 없다. 앱의 작업은 모두 구조화 출력(JSON)이나 텍스트 스트림으로 돈다.

### vLLM

GPU 서버에서(예: SKT A.X 3.1, Apache-2.0):

```bash
vllm serve skt/A.X-3.1 --served-model-name a.x-3.1 --max-model-len 32768 --api-key "$IA_LLM_API_KEY"
```

화면에는 서버 주소 `http://<GPU 서버>:8000/v1`, 모델 이름 `a.x-3.1`, API 키 환경변수 `IA_LLM_API_KEY`(앱 서버에도 같은 값)를 적는다. Qwen3 계열은 추가 요청 필드에 `{"chat_template_kwargs": {"enable_thinking": false}}`를 넣어 추론을 끈다.

### Ollama

시험·소규모용. 동시 면접이 많으면 vLLM을 쓴다.

```bash
ollama pull gemma4:e4b
```

다른 PC에서 부르려면 Ollama를 `OLLAMA_HOST=0.0.0.0`으로 띄운다. 화면에는 서버 주소 `http://<host>:11434/v1`, 모델 이름 `gemma4:e4b`, API 키는 비운다. Ollama의 OpenAI 형식 API는 요청마다 컨텍스트 길이를 정할 수 없어서, 서류 선별처럼 입력이 길면 서버의 `OLLAMA_CONTEXT_LENGTH`(또는 Modelfile의 `num_ctx`)로 늘린다.

### 사내 게이트웨이

게이트웨이가 OpenAI 형식을 그대로 넘겨주면 같은 provider로 붙는다. 사내 LLM(예: 사내 전용 모델)이 OpenAI 형식 API를 주면 마찬가지다.

| 옵션 | 예 |
| --- | --- |
| 서버 주소 | `https://llm-gateway.example.corp/openai-compat/v1` |
| API 키 환경변수 이름 | 게이트웨이가 `Authorization: Bearer`를 쓰면 `IA_LLM_API_KEY`, 아니면 비움 |
| 추가 헤더 | `X-Team: hr-ai` 와 `X-Gateway-Key: ${IA_GATEWAY_KEY}` (두 줄) |
| 구조화 출력 방식 | 게이트웨이가 `response_format`을 넘기지 못하면 `prompt` |

## 로컬 Whisper STT (`faster_whisper`)

OpenAI Whisper를 이 PC의 CPU에서 돌린다(faster-whisper, CTranslate2 int8, MIT). 한국어 고정, 내장 Silero VAD로 발화를 나누고, 실시간(부분·확정 전사)과 사후(파일 전사) 둘 다 된다. 음성은 PC 밖으로 나가지 않는다.

1. `uv sync --extra whisper`
2. 모델 설정 > STT 사후(또는 실시간) > 변경 > "Whisper (로컬)" > 모델 크기 카드의 "다운로드". small 486MB, medium 1.5GB, large-v3 3.1GB, large-v3-turbo 1.6GB. Hugging Face에서 커밋 고정·sha256 검증으로 받아 `weights/`(git 제외, `IA_WEIGHTS_DIR`)에 둔다. 끊겨도 이어받는다. 미러는 `HF_ENDPOINT`.
3. "기술 용어 힌트"에 자주 나오는 용어를 적는다(예: 반도체 공정, CMP, 식각, 수율). 30초 창마다 프롬프트로 들어간다.
4. 연결 테스트, 사유, 적용. 되돌리려면 변경 이력의 "되돌리기".

측정 요약(이 노트북, GPU 없음): 정확도는 medium 이상이 충분하고 small은 한국어에서 눈에 띄게 틀린다. Whisper는 호출마다 30초 창을 통째로 인코딩해 짧은 발화도 같은 비용이 들어, 이 CPU로는 실시간 전사가 발화 끝 뒤 수 초~십여 초 늦다. 화면의 권장(실시간 medium, 사후 large-v3)은 정확도 기준이다.

실시간 면접 화면에서 마이크(또는 진단용 샘플 음성)를 켜면 STT 실시간 설정이 그 음성을 전사한다. 마이크를 켜기 전에는 가상 지원자 대본(텍스트)이 흘러 fake STT만 받아 적는다(Whisper면 감사 로그 `transcript.unsupported_audio`, 수기 답변). GPU가 없으면 STT 실시간은 small, STT 사후는 large-v3로 두고 "면접 뒤 녹음 재전사"를 켜 기록을 정확하게 남길 수 있다([audio-input.md](audio-input.md) 8장).

측정 다시 하기 (정답 전사가 있는 WAV 목록 JSON):

```bash
uv run python scripts/bench_whisper.py --manifest clips.json --sizes small medium large-v3-turbo large-v3
```

## 로컬 임베딩 BGE-M3 (`bge_m3`)

BAAI의 다국어 임베딩 모델 BGE-M3(MIT)를 이 PC의 CPU에서 돌린다. 공식 ONNX 변환본을 ONNX Runtime(MIT)과 tokenizers(Apache-2.0)로 읽어 torch가 필요 없다. 의미 벡터(밀집, 1024차원)와 단어 일치 가중치(희소)를 함께 내고, 검색 점수는 의미 유사도 + `sparse_weight` × 단어 일치다. 질문·답변 텍스트는 PC 밖으로 나가지 않는다. 쓰는 곳은 [question-bank.md](question-bank.md), 측정은 [embedding-benchmark.md](embedding-benchmark.md).

1. `uv sync --extra whisper --extra ocr --extra embedding` (onnxruntime·tokenizers는 faster-whisper도 쓰는 패키지라 대부분 이미 있다)
2. 모델 설정 > 임베딩 > 변경 > "BGE-M3 (로컬)" > 모델을 고르고 모델 카드의 "다운로드". 받기 전에는 요구 조건 미충족으로 테스트·적용이 안 된다. 희소 헤드(`sparse_linear.pt`)는 바이트로만 읽고 pickle은 실행하지 않는다. 모든 파일을 커밋 고정·sha256 검증으로 받는다.
   - **BGE-M3 (int8 ONNX)**, 권장, 0.59GB: Hugging Face `Xenova/bge-m3` 커밋 `4de1325`의 int8 변환본(transformers.js, MIT)과 BAAI의 희소 헤드를 `weights/bge-m3/onnx-int8/`에. 이 노트북에서 답변 1건 0.28초, 메모리 약 0.9GB. 평가 세트에서 검색 품질 차이는 37개 중 1개([embedding-benchmark.md](embedding-benchmark.md) "int8 양자화")
   - **BGE-M3 (fp32 ONNX)**, 2.29GB: BAAI/bge-m3 커밋 `5617a9f`의 공식 ONNX를 `weights/bge-m3/onnx-fp32/`에. 답변 1건 0.44~0.9초, 메모리 약 1.6GB
   - 둘은 벡터가 조금 달라 색인 키가 다르다. 서로 바꾸면 백그라운드로 다시 색인한다. 권장값이 바뀌어도 이미 적용한 설정은 그대로다
3. 옵션: 최대 길이(512토큰), CPU 스레드(자동 = 코어 수의 절반, 최대 6), 검색 설정 셋(단어 일치 가중치 0.3, 같은 질문으로 볼 유사도 0.85, 질문 은행 제안 최소 점수 0.55). 검색 설정은 바꿔도 벡터를 다시 만들지 않고 모델도 다시 올리지 않는다.
4. 연결 테스트, 사유, 적용. 적용하면 "임베딩 색인" 칸에 새 색인 진행률이 보이고, 끝날 때까지 이전 색인(이전 모델)으로 검색한다. 실패하면 이전 색인이 남고 "다시 만들기"로 다시 시도한다.

메모리는 서버 프로세스에 fp32 약 1.6GB, int8 약 0.9GB가 더해진다(Whisper medium과 함께 2.5GB, 1.9GB). ONNX Runtime은 Intel OpenMP를 싣지 않아 Whisper(CTranslate2)와 한 프로세스에서 돌아도 DLL이 충돌하지 않는다. Vertex AI 임베딩은 카탈로그에만 있다(구현 전).

## 음성 입력 (VAD, 답변 끝 판정, 잡음 억제)

실시간 면접 마이크 경로의 설정이다([audio-input.md](audio-input.md)). 음성은 서버 밖으로 나가지 않는다.

- **음성 구간 (VAD)**: Silero VAD. faster-whisper 패키지 안의 모델 파일을 쓰고 불러올 때 sha256을 확인한다(내려받을 것 없음, `uv sync --extra whisper`). 옵션: 말소리 기준(0.5), 말소리 뒤 여유(300ms), 답변 시작으로 볼 최소 말소리(250ms). 연결 테스트는 내장 샘플(또는 녹음·파일)에서 찾은 말소리 구간을 보여 준다.
- **답변 끝 판정**: 침묵 기준(ms 조정) 또는 Smart Turn v3.2. Smart Turn은 모델 카드의 "다운로드 9MB"로 받는다(Hugging Face `pipecat-ai/smart-turn-v3` 커밋 고정, sha256 검증, `weights/smart-turn/v3.2-cpu/`). 옵션: 판정 시작 침묵(1,000ms), 끝 판정 기준(0.8), 최대 침묵(3,000ms). 연결 테스트는 샘플 뒤 3초 무음을 붙여 마지막 말소리 몇 초 뒤에 답변 끝으로 보는지 보여 준다. 실사용 기본(`config/providers.yaml`)은 Smart Turn이고, 파일이 없으면 침묵 2초로 판정한다.
- **서버 잡음 억제**: "끔"만 쓸 수 있다. RNNoise·DeepFilterNet은 구현 전(측정 계획은 [audio-input.md](audio-input.md) 7장).

## 서류 읽기

| 역할 | 고르는 것 | 기본 |
| --- | --- | --- |
| 읽기 방식 | 자동(텍스트 우선, 없거나 깨지면 OCR) / 항상 OCR / 텍스트만(OCR 없음, 스캔은 보류), 문서 속 그림 OCR 켬·끔, 깨짐 판정 민감도(낮음·보통·높음), OCR 해상도(200dpi), 신뢰도 경고 기준(0.8) | 자동, 그림 OCR 켬, 보통 |
| OCR 엔진 | PaddleOCR(PP-OCRv5 한국어, 이 PC) / Tesseract(이 PC) / Google Document AI(사내 GCP, 구현 전) / Naver CLOVA OCR(외부, 구현 전) / Fake | PaddleOCR mobile |
| PDF 텍스트 추출 | pdfplumber (구현이 하나라 상태만) | |
| HWP·HWPX 읽기 | syhwp + OWPML(파이썬) / hwplib(Java, 구현 전) | syhwp |
| 구형 오피스 변환 | LibreOffice(헤드리스) (구현이 하나라 상태만) | |

규칙(쪽별 선택, 깨짐 판정, 증명사진, 오독 대책)과 형식별 지원 현황은 [document-reading.md](document-reading.md).

### 로컬 OCR 설치

1. PaddleOCR: `uv sync --extra whisper --extra ocr`(paddleocr 3.7.0, paddlepaddle 3.2.2 CPU). 모델 설정 > OCR 엔진 > 변경 > PaddleOCR > 모델 카드의 "다운로드"(mobile 32MB 권장, server 116MB). Hugging Face에서 커밋 고정·sha256 검증으로 받아 `weights/paddleocr/`에 둔다.
2. Tesseract(비교용): 프로그램을 설치하고(`winget install UB-Mannheim.TesseractOCR`, 다른 곳이면 `TESSERACT_CMD`), 모델 카드의 "다운로드"로 한국어·영어 데이터(best 약 28MB, fast 약 6MB, GitHub tessdata, 커밋 고정·sha256)를 받는다.
3. 연결 테스트(내장 샘플 또는 스캔 파일), 사유, 적용. 되돌리려면 변경 이력의 "되돌리기". PaddleOCR은 서버와 다른 작업 프로세스에서 돌아(faster-whisper와 DLL이 충돌해서, [document-reading.md](document-reading.md)) 테스트·적용 때 그 프로세스를 띄우고 모델을 올리느라 10초 안팎 걸린다.

구형 .doc·.ppt는 LibreOffice가 있어야 읽는다(`winget install TheDocumentFoundation.LibreOffice`, 다른 곳이면 `SOFFICE_CMD`). 없으면 카드에 "프로그램 LibreOffice 없음"이 보이고 그런 서류는 "변환기 없음"으로 거부된다.

외부 OCR(CLOVA)은 서류 그림을 회사 밖으로 보낸다. 고르면 경고가 나오고, 확인해야 테스트되고 사유를 적어야 적용된다. 자격증명은 화면에서 받지 않는다(서버 환경변수).

## provider 추가하기

1. `providers/base.py`의 인터페이스를 구현한다(`model` 이름, 필요하면 `warm_up`에서 가중치 로드). OCR은 `OCRProvider.recognize(image) -> OcrResult`(줄마다 텍스트·신뢰도·위치)와 `version`.
2. `providers/registry.py`에 impl 이름을 등록한다.
3. `providers/catalog.py`에 역할, 데이터 위치, 옵션 스키마, 요구 조건(패키지·환경변수·자격증명·가중치)을 적는다.
4. 연결 테스트가 통과하면 관리자 화면에서 고를 수 있다.
