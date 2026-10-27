# AI 모델 설정 (관리자)

LLM, STT, 임베딩, 화자분리와 서류 읽기 도구(OCR 엔진 등)는 관리자 화면에서 고르고, 테스트하고, 서버 재시작 없이 바꾼다. API는 [api-contract.md](api-contract.md) "관리자 > 모델 설정", 고를 때의 기준은 [model-selection.md](model-selection.md), 측정은 [whisper-benchmark.md](whisper-benchmark.md)와 [ocr-benchmark.md](ocr-benchmark.md), 서류 읽기 규칙은 [document-reading.md](document-reading.md).

## 화면

사이드바 "관리자 > 모델 설정"(또는 Ctrl+K에서 "모델"). 관리자만 보이고, API(`/api/admin/models/*`)도 관리자가 아니면 403이다. 관리자는 `Interviewer.is_admin`이며, SSO가 붙으면 그룹으로 채운다.

- **역할 카드 11개, 두 묶음**: AI 모델(LLM 주 모델, LLM 선별용, STT 실시간, STT 사후, 임베딩, 화자분리, 그 아래 임베딩 색인 상태)과 서류 읽기(읽기 방식, OCR 엔진, PDF 텍스트 추출, HWP·HWPX 읽기, 구형 오피스 변환). 현재 provider와 실제 모델 이름, 사용 가능 여부(안 되면 이유), 데이터 위치 배지(이 PC / 사내 GCP / 외부), 마지막 변경(누가·언제·사유).
- **변경**: provider 선택 → 모델·옵션 → 요구 조건 확인 → (외부 전송 경고) → 연결 테스트 → 사유 → 적용.
  - 요구 조건은 네트워크 없이 본다: 구현 여부, 패키지, 환경변수·자격증명 파일이 있는지(값은 보지 않음), 모델 파일.
  - API 키·자격증명은 화면에서 받지 않는다. 서버 환경변수나 Secret Manager로 넣는다.
  - 회사 밖으로 데이터를 보내는 provider는 경고를 확인해야 테스트되고, 사유까지 적어야 적용된다.
- **적용**은 재시작 없이 바로 된다. 진행 중인 면접은 시작할 때의 모델을 끝까지(실시간 전사, 꼬리질문, 종료 뒤 AI 채점까지) 쓰고, 새 면접부터 새 설정을 쓴다. 처리 중인 서류도 시작할 때의 읽기 설정으로 끝난다. 결과에는 실제 쓴 모델 이름(서류는 읽기 도구와 버전)이 남는다.
- **변경 이력**에서 이전 설정으로 되돌린다. 활성 설정과 이력은 DB(`ai_model_settings`, `ai_model_changes`, Alembic 0004)에 있고, YAML(`IA_PROVIDERS_FILE`)은 처음 기동할 때의 기본값으로만 쓴다.
- 모든 테스트·변경·다운로드는 감사 로그에 남는다. 테스트는 결과 수치만 남고, 전사나 응답 본문은 남지 않는다.

## 연결 테스트

| 역할 | 테스트 |
| --- | --- |
| LLM | 지원자 데이터가 없는 고정 문장으로 구조화 출력(JSON)과 간단한 지시 수행을 본다 |
| STT | 내장 샘플(FLEURS 한국어 11.5초, 정답과 비교한 글자 오류율), 마이크 녹음(5~10초), 파일(60초·10MB 이하). 역할의 실제 경로로 돈다(실시간 = 스트리밍, 사후 = 파일 전사). 올린 음성은 테스트가 끝나면 지운다 |
| 임베딩 | 지원자 데이터가 없는 고정 문장 세 개(문장, 같은 약어 FDC를 쓴 비슷한 문장, 무관한 문장)로 차원, 희소 가중치 유무, 비슷한 문장이 무관한 문장보다 가까운지. 아니면 실패 |
| 화자분리 | 샘플의 화자 구간 수 |
| 서류 읽기 | 역할별 내장 가상 이력서(OCR은 글자 그림 PNG, 읽기 방식은 텍스트+스캔 혼합 PDF, HWP는 HWPX, 구형 변환은 .doc) 또는 올린 파일(10MB). 테스트하는 설정 + 나머지 서류 읽기 역할의 활성 설정으로 읽고, 쪽마다 방법·이유·도구·신뢰도·시간, 그림마다 판단, 비식별화한 미리보기를 보여 준다. 내장 샘플은 정답과 비교한 글자 오류율도. 원문은 화면에도 감사 로그에도 없다 |

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

## 로컬 임베딩 BGE-M3 (`bge_m3`)

BAAI의 다국어 임베딩 모델 BGE-M3(MIT)를 이 PC의 CPU에서 돌린다. 공식 ONNX 변환본을 ONNX Runtime(MIT)과 tokenizers(Apache-2.0)로 읽어 torch가 필요 없다. 의미 벡터(밀집, 1024차원)와 단어 일치 가중치(희소)를 함께 내고, 검색 점수는 의미 유사도 + `sparse_weight` × 단어 일치다. 질문·답변 텍스트는 PC 밖으로 나가지 않는다. 쓰는 곳은 [question-bank.md](question-bank.md), 측정은 [embedding-benchmark.md](embedding-benchmark.md).

1. `uv sync --extra whisper --extra ocr --extra embedding` (onnxruntime·tokenizers는 faster-whisper도 쓰는 패키지라 대부분 이미 있다)
2. 모델 설정 > 임베딩 > 변경 > "BGE-M3 (로컬)" > 모델 카드의 "다운로드 2.3GB". Hugging Face BAAI/bge-m3의 커밋 `5617a9f`에서 ONNX 모델·데이터·토크나이저와 희소 헤드(`sparse_linear.pt`, 바이트로만 읽고 pickle은 실행하지 않음)를 sha256 검증으로 받아 `weights/bge-m3/onnx-fp32/`에 둔다. 받기 전에는 요구 조건 미충족으로 테스트·적용이 안 된다.
3. 옵션: 최대 길이(512토큰), CPU 스레드(자동 = 코어 수의 절반, 최대 6), 검색 설정 셋(단어 일치 가중치 0.3, 같은 질문으로 볼 유사도 0.85, 질문 은행 제안 최소 점수 0.55). 검색 설정은 바꿔도 벡터를 다시 만들지 않고 모델도 다시 올리지 않는다.
4. 연결 테스트, 사유, 적용. 적용하면 "임베딩 색인" 칸에 새 색인 진행률이 보이고, 끝날 때까지 이전 색인(이전 모델)으로 검색한다. 실패하면 이전 색인이 남고 "다시 만들기"로 다시 시도한다.

메모리는 서버 프로세스에 약 1.6GB가 더해진다(Whisper medium과 함께 2.5GB). ONNX Runtime은 Intel OpenMP를 싣지 않아 Whisper(CTranslate2)와 한 프로세스에서 돌아도 DLL이 충돌하지 않는다. Vertex AI 임베딩은 카탈로그에만 있다(구현 전).

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
