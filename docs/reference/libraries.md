# 라이브러리·모델·클라우드 서비스

2026-10-27 · 이 프로젝트가 쓰거나 검토한 것 전부(2026-10-28 GCP 전제 철회 반영). 고른 이유는 [model-selection.md](../model-selection.md), 측정은 `*-benchmark.md`, 사용법은 [ai-models.md](../ai-models.md).

읽는 법:

- **라이선스**: 패키지는 설치된 메타데이터(`importlib.metadata`, `node_modules/*/package.json`)로, 설치 안 된 것은 PyPI로 확인했다. 모델은 코드와 가중치 라이선스를 따로 적는다.
- **비용**: 무료 / 유료(과금 단위, 가격은 모두 2026-10-27 확인). 1·2장은 모두 무료라 비용 칸을 뺐다.
- **상업**: 회사 내부 서비스에 써도 되는가. MIT·BSD·Apache·ISC는 고지 의무만 지키면 된다. MPL은 그 파일을 고쳐 배포할 때만 고친 파일을 공개한다. AGPL·비상업(NC)은 안 된다. GPL은 7장.
- **데이터**: 로컬 = 이 PC나 회사 서버 안에서만 돈다. 설정한 사내 서버 = 관리자가 주소를 적은 사내 모델 서버(오픈소스 LLM). 외부 클라우드 (Google) = Google Cloud 서비스, 회사 밖이다. 외부 = 회사 밖 API. 관리자 화면의 데이터 위치 배지와 같다. 2026-10-21에는 Google 서비스를 "사내 GCP"(이 PoC를 위해 직접 만들 GCP 프로젝트)로 불렀으나, 2026-10-28 GCP를 쓰지 않기로 하며 "외부 클라우드 (Google)"로 바꿨다.
- **상태**: 사용 중 / 후보(카탈로그나 설정 파일에 있고 구현 전) / 검토만 / 쓰지 않음(사유).

## 1. 백엔드 (파이썬)

모두 로컬, 상업 사용 가능. `pyproject.toml` 기준, 버전은 이 PC에 설치된 것.

| 이름 | 버전 | 용도 | 라이선스 | 상태 |
| --- | --- | --- | --- | --- |
| FastAPI, Starlette | 0.156.4, 1.9.0 | REST·SSE API | MIT, BSD-3-Clause | 사용 중 |
| Uvicorn | 0.54.0 | ASGI 서버 | BSD-3-Clause | 사용 중 |
| Pydantic, pydantic-settings | 2.14.1, 2.16.1 | 스키마, 환경변수 설정 | MIT | 사용 중 |
| SQLAlchemy, Alembic | 2.1.5, 1.20.0 | ORM, 마이그레이션(0001~0007) | MIT | 사용 중 |
| cryptography | 50.0.2 | 컬럼 암호화(Fernet) | Apache-2.0 또는 BSD-3-Clause | 사용 중 |
| PyYAML | 6.0.2 | 설정 파일 | MIT | 사용 중 |
| python-multipart | 0.0.32 | 업로드·사이트 첨부 multipart | Apache-2.0 | 사용 중 |
| NumPy | 2.3.5 | 메모리 벡터 검색 | BSD-3-Clause | 사용 중 |
| anthropic (`gcp` extra) | 설치 안 됨 (PyPI 최신 2.3.0) | Vertex AI의 Claude 호출 | Apache-2.0 (PyPI) | 쓰지 않음 (2026-10-28 GCP 철회. 외부 클라우드 승인 시 대안) |
| google-cloud-speech (`gcp` extra) | 설치 안 됨 (PyPI 최신 2.41.0) | Speech-to-Text v2 | Apache-2.0 (PyPI) | 외부 클라우드 대안 (승인 시, 10·11단계) |
| pytest, pytest-asyncio | 9.1.1, 1.4.0 | 테스트 (dev) | MIT, Apache-2.0 | 사용 중 |
| httpx, httpx2 | 0.28.1, 2.16.0 | 테스트 클라이언트 (dev) | BSD-3-Clause | 사용 중 |
| reportlab, Pillow | 5.0.1, 13.0.0 | 가상 이력서 만들기 (dev), 그림 처리 | BSD, MIT-CMU | 사용 중 |

## 2. 프론트엔드

모두 로컬(브라우저), 상업 사용 가능. `frontend/package.json` 기준. 스택 설명은 [frontend.md](../frontend.md).

| 이름 | 버전 | 용도 | 라이선스 |
| --- | --- | --- | --- |
| Vue, Vue Router | 3.5.43, 5.4.0 | 화면, 라우팅 | MIT |
| Reka UI | 2.11.0 | 접근성 있는 기본 컴포넌트 (shadcn-vue 방식) | MIT |
| TanStack Query (`@tanstack/vue-query`) | 5.104.1 | 서버 상태 | MIT |
| Tailwind CSS, `@tailwindcss/vite`, tw-animate-css | 4.3.3, 4.3.3, 1.4.0 | 스타일 | MIT |
| class-variance-authority, clsx, tailwind-merge | 0.7.1, 2.1.1, 3.7.0 | 클래스 조합 | Apache-2.0, MIT, MIT |
| Chart.js, vue-chartjs | 4.5.1, 5.3.4 | 점수 차트 | MIT |
| vue-sonner | 2.0.9 | 알림 | MIT |
| `@lucide/vue` | 1.53.0 | 아이콘 | ISC |
| Pretendard | 1.3.9 | 폰트 (자체 호스팅) | OFL-1.1 (폰트만 따로 팔지 않으면 됨) |
| Vite, vue-tsc, TypeScript | 8.3.3, 3.3.12, 6.0.3 | 빌드, 타입 검사 | MIT, MIT, Apache-2.0 |
| Vitest, Testing Library, jsdom, MSW | 5.0.3, 8.1.0, 30.1.2, 3.0.2 | 테스트, 모의 API | MIT |
| ESLint, typescript-eslint, eslint-plugin-vue | 10.12.0, 8.71.1, 10.11.1 | 린트 | MIT |

## 3. 서류 읽기

규칙과 형식별 지원 현황은 [document-reading.md](../document-reading.md), OCR 측정은 [ocr-benchmark.md](../ocr-benchmark.md).

| 이름 | 용도 | 라이선스 | 비용 | 데이터 | 상태 |
| --- | --- | --- | --- | --- | --- |
| pdfplumber 0.11.10 (+ pdfminer.six) | PDF 텍스트·표·주석 | MIT | 무료 | 로컬 | 사용 중 |
| pypdfium2 5.14.0 | PDF 쪽을 그림으로 (OCR용) | BSD-3-Clause, Apache-2.0 (PDFium) | 무료 | 로컬 | 사용 중 |
| python-docx 1.2.0, python-pptx 1.0.2 | DOCX, PPTX | MIT | 무료 | 로컬 | 사용 중 |
| beautifulsoup4 4.15.0, lxml 6.1.3 | HTML, HWPX(XML) | MIT, BSD-3-Clause | 무료 | 로컬 | 사용 중 |
| syhwp 0.0.8 | HWP 5.0 컨테이너·레코드 | MIT | 무료 | 로컬 | 사용 중. 1인 프로젝트라 버전 고정 |
| olefile 0.47 | OLE 컨테이너(HWP 문서 정보) | BSD | 무료 | 로컬 | 사용 중 |
| Pillow 13.0.0 | JPG·PNG, EXIF 방향 | MIT-CMU | 무료 | 로컬 | 사용 중 |
| LibreOffice 26.8 (별도 프로그램) | 구형 .doc·.ppt → .docx·.pptx | MPL-2.0 | 무료 | 로컬 | 사용 중 |
| PaddleOCR 3.7.0 + PaddlePaddle 3.2.2 (+ PaddleX, OpenCV) | 로컬 OCR 엔진 | Apache-2.0 | 무료 | 로컬 | 사용 중 (기본) |
| PP-OCRv5 mobile 검출 + 한국어 인식 모델 | OCR 가중치 (32MB) | Apache-2.0 (Hugging Face 모델 카드) | 무료 | 로컬 | 사용 중 |
| Tesseract 5.4 + tessdata best·fast | 로컬 OCR 엔진 | Apache-2.0 | 무료 | 로컬 | 비교용. 한국어 오류가 많다(글자 오류율 평균 29~31%, [ocr-benchmark.md](../ocr-benchmark.md)) |
| hwplib (Java) | HWP 읽기 대안 | Apache-2.0 | 무료 | 로컬 | 후보. Java 런타임이 필요하다 |
| Google Document AI (Enterprise Document OCR) | 클라우드 OCR | 상용 | 1,000쪽당 $1.50 (6장) | 외부 클라우드 (Google, 리전 us·eu) | 외부 클라우드 대안 (카탈로그만, 승인 시) |
| NAVER CLOVA OCR | 클라우드 OCR | 상용 | 호출당 3원 (6장) | 외부 (서류 그림이 회사 밖으로) | 후보 (카탈로그만) |
| pyhwp | HWP 읽기 | AGPL-3.0 | 무료 | 로컬 | 쓰지 않음. AGPL은 네트워크로 서비스하면 소스 공개 의무가 생긴다 |
| PyMuPDF | PDF 읽기·렌더 | AGPL-3.0 또는 Artifex 상용 | 상용 라이선스는 유료 | 로컬 | 쓰지 않음. 같은 이유 |

OCR 엔진 비교(정확도·속도·메모리)는 [ocr-benchmark.md](../ocr-benchmark.md)에 있다. 요약: PaddleOCR mobile은 한국어 서류 글자 오류율 평균 0.5%, 쪽당 4~5초, Tesseract는 29~31%로 비교용. 클라우드 OCR은 서류 그림(증명사진·이름 포함)을 그대로 보내므로, 쓰려면 비식별화 앞 단계에서 원본이 나가는 것을 보안 승인받아야 한다.

## 4. AI 모델 (LLM·임베딩)

역할별 기준(선별은 비용, 채점은 품질, 꼬리질문은 속도)은 [model-selection.md](../model-selection.md) 1·5장, 임베딩 결정과 측정은 같은 문서 6장과 [embedding-benchmark.md](../embedding-benchmark.md). 사내 서버에 올릴 오픈 웨이트 LLM(라이선스·출처 국가·GPU 메모리·한국어 근거·작업별 권장)은 [llm.md](llm.md). LLM에는 비식별 텍스트만 가고, 호출 직전 가드가 다시 본다.

| 이름 | 용도 | 라이선스 | 비용 (100만 토큰당 입력 / 출력, global 엔드포인트) | 데이터 | 상태 |
| --- | --- | --- | --- | --- | --- |
| 오픈소스 모델 서버 (`open_model_server`: vLLM·Ollama·SGLang의 OpenAI 형식 API, httpx2로 호출) | LLM 주 모델·선별 | 연결 코드는 프로젝트 코드와 httpx2(BSD-3-Clause), 모델은 모델마다 다름([llm.md](llm.md)) | 무료 (사내 GPU 비용) | 설정한 사내 서버 | 구현, `providers.yaml` 기본값 (2026-10-28, 예시 `skt/A.X-3.1`). 실제 사내 서버 연결 전 |
| Claude API (`anthropic_api`: Opus 5.5·Sonnet 5.5·Haiku 5.5, 공식 Python SDK `anthropic` 1.13.0으로 직접 호출) | 외부 개발 환경 테스트: 시드 데이터로 꼬리질문·채점·역량 사전 초안 | SDK MIT, 모델 상용 | Opus 5.5 $4.00 / $20.00, Sonnet 5.5 $2.00 / $10.00, Haiku 5.5 $0.10 / $0.50 (Anthropic API 가격) | 외부 (Anthropic) | 구현 (2026-10-28). 외부 개발 환경 테스트용, 사내 반입 대상 아님 ([ai-models.md](../ai-models.md) "Claude API") |
| Claude Opus 5.5 (Vertex AI) | LLM 주 모델: 채점·역량 사전·꼬리질문 | 상용 | $4.00 / $20.00 | 외부 클라우드 (Google) | 쓰지 않음 (2026-10-28 사용자: GCP·OpenAI 서비스 안 씀) |
| Claude Sonnet 5.5 (Vertex AI) | 속도·성능 균형 | 상용 | $2.00 / $10.00 | 외부 클라우드 (Google) | 쓰지 않음 (2026-10-28 사용자: GCP·OpenAI 서비스 안 씀) |
| Claude Haiku 5.5 (Vertex AI) | 서류 선별 (대량) | 상용 | 입력 10만 토큰까지 $0.10 / $0.50, 넘으면 $0.50 / $2.50 | 외부 클라우드 (Google) | 쓰지 않음 (2026-10-28 사용자: GCP·OpenAI 서비스 안 씀) |
| Claude Fable 5.1 (Vertex AI) | 가장 높은 성능 | 상용 | $10.00 / $50.00 | 외부 클라우드 (Google) | 쓰지 않음 (2026-10-28 사용자: GCP·OpenAI 서비스 안 씀) |
| Gemini (Vertex AI), 사내 LLM(`samsung_gauss`) | LLM 대안 | | 확인 안 함 | | 조사 안 함. 사내 LLM이 OpenAI 형식 API를 주면 `open_model_server`로 붙는다 |
| Fake LLM | 흐름·화면 확인 | 프로젝트 코드 | 무료 | 로컬 | 사용 중 (`providers.fake.yaml`) |
| BGE-M3 (BAAI/bge-m3, 공식 ONNX) | 임베딩: 밀집 1024차원 + 희소 | MIT | 무료 | 로컬 | 사용 중 (2026-10-27 결정). fp32 원본 |
| BGE-M3 int8 (Xenova/bge-m3, transformers.js 변환) | 같은 모델의 int8 가중치(0.59GB), BAAI 희소 헤드와 함께 | MIT | 무료 | 로컬 | 권장 (2026-10-28, [embedding-benchmark.md](../embedding-benchmark.md) "int8 양자화") |
| ONNX Runtime 1.31, tokenizers 0.23 | BGE-M3 실행 | MIT, Apache-2.0 | 무료 | 로컬 | 사용 중 |
| FlagEmbedding + torch | BGE-M3 공식 파이썬 라이브러리 | MIT (+ torch BSD, transformers Apache-2.0) | 무료 | 로컬 | 쓰지 않음 (8장) |
| Vertex AI gemini-embedding-001 | 임베딩 대안 (최대 3072차원, 2048토큰, 한국어 지원) | 상용 | "1,000개"당 $0.00015, 배치 $0.00012. 단위(글자·토큰)는 확인 필요 | 외부 클라우드 (Google), 서울 리전 있음 | 외부 클라우드 대안 (카탈로그만) |
| Vertex AI text-multilingual-embedding-002 | 임베딩 대안 (768차원, 한국어 지원) | 상용 | "1,000개"당 $0.000025 | 외부 클라우드 (Google), 리전 확인 필요 | 외부 클라우드 대안 (카탈로그만) |
| Fake 임베딩 | 흐름 확인 | 프로젝트 코드 | 무료 | 로컬 | 사용 중 (`providers.fake.yaml`) |

- **Vertex AI의 Claude 5.x는 global 엔드포인트와 us·eu 멀티 리전에서만 된다.** 지역 엔드포인트는 Sonnet 4.6 이전 모델만 받고, 서울(asia-northeast3)에는 Claude가 없다. us·eu 멀티 리전은 global보다 10% 비싸다(Opus 5.5 $4.40 / $22.00). 가격 페이지에는 europe-west1·asia-southeast1 탭에 Haiku 5.5가 보여 문서와 엇갈린다(확인 필요).
- **학습**: Google은 사전 허락이나 지시 없이 고객 데이터를 모델 학습·미세조정에 쓰지 않는다고 적고, 이것이 Vertex AI의 모든 관리형 모델에 적용된다고 한다. Anthropic 문서는 데이터 처리를 Google Cloud가 맡는다고만 적는다.
- **임베딩 비교**: BGE-M3는 회사 밖으로 나가는 것이 없고 희소(단어 일치) 점수를 같이 내서 약어가 겹치는 답변의 1위 적중이 87.5% → 100%로 올랐다([embedding-benchmark.md](../embedding-benchmark.md)). Vertex 임베딩은 서버 메모리(+1.6GB)가 들지 않는 대신 비식별 답변이 회사 밖(Google)으로 가고, 희소(단어 일치) 출력이 있는지는 확인하지 못했다. 모델을 바꾸면 백그라운드로 재색인한다.
- OpenAI text-embedding-3-large는 100만 토큰당 $0.13이다(참고, 카탈로그에 없음).

## 5. 음성

STT 서비스별 비교는 [stt.md](stt.md), 화자분리 모델은 [diarization.md](diarization.md), 앞단 처리는 [audio-quality.md](audio-quality.md).

| 이름 | 용도 | 라이선스 (코드 / 가중치) | 비용 | 상업 | 데이터 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| faster-whisper 1.2.1 + CTranslate2 4.8.2 | 로컬 STT 실행기 | MIT / Whisper 가중치 MIT | 무료 | 가능 | 로컬 | 사용 중 (`faster_whisper`) |
| Whisper small·medium·large-v3·large-v3-turbo | STT 가중치 | MIT | 무료 | 가능 | 로컬 | 사용 중. `providers.yaml` 기본값은 실시간 small(GPU 없을 때, [audio-input.md](../audio-input.md) 8장), 사후 large-v3 + 재전사. 실시간 정확도만 보면 medium 이상 |
| PyAV 19.0.1 (+ 함께 오는 FFmpeg 9.0.2) | 오디오 파일을 16kHz PCM으로 풀기. faster-whisper의 의존성 | BSD-3-Clause / FFmpeg는 7장 | 무료 | 확인 필요 (7장) | 로컬 | 사용 중 |
| Silero VAD (faster-whisper에 포함, v6 ONNX) | 말 구간 찾기 | MIT | 무료 | 가능 | 로컬 | 사용 중 |
| Google Speech-to-Text v2 (Chirp 3) | 실시간·사후 STT, 배치 화자분리 | 상용 | 유료, [stt.md](stt.md) | 계약 | 외부 클라우드 (Google, 리전 us·eu) | 외부 클라우드 대안 (`google_stt_v2`, 구현 전. `providers.yaml`의 화자분리 기본값으로 아직 남아 있음. STT 기본값은 2026-10-28 로컬 Whisper로 바꿈) |
| NAVER CLOVA Speech | 실시간·사후 STT | 상용 | 유료 | 계약 | 외부 (한국) | 검토만 (`providers.yaml` 대안 주석) |
| Azure AI Speech, AWS Transcribe, 리턴제로, OpenAI 전사 API | STT | 상용 | 유료 | 계약 | 외부 | 검토만 |
| pyannote.audio + speaker-diarization-community-1 | 로컬 화자분리 | MIT / CC-BY-4.0 (Hugging Face 약관 동의 후 받음) | 무료 | 가능 (출처 표시) | 로컬 | 후보 (`providers.yaml` 대안 주석) |
| pyannote speaker-diarization-3.1 | 로컬 화자분리 (이전 판) | MIT / MIT (약관 동의) | 무료 | 가능 | 로컬 | 검토만 |
| pyannoteAI precision-2, Live-1 | 클라우드 화자분리 | 상용 | 시간당 €0.096~0.198 | 계약 | 외부 (EU) | 검토만 |
| NVIDIA NeMo + Streaming Sortformer v2 / Nemotron-3-Diarization | GPU 실시간 화자분리 | Apache-2.0 / CC-BY-4.0, OpenMDW-1.1 | 무료 | 가능 | 로컬 (GPU) | 검토만. GPU 서버가 생기면 |
| NVIDIA Sortformer v1, DiariZen | 화자분리 | Apache-2.0·MIT / CC BY-NC 4.0 | 무료 | **불가** | 로컬 | 쓰지 않음. 가중치가 비상업 전용 |
| WhisperX | 전사 + 단어 시각 + 화자분리 묶음 | BSD-2-Clause / pyannote 약관 | 무료 | 가능 | 로컬 | 검토만 |
| Pipecat Smart Turn v3.2 | 소리로 답변 끝 판단 | BSD-2-Clause / 같음 (8MB) | 무료 | 가능 | 로컬 | 후보 (마이크 입력 때 시험) |
| LiveKit turn detector | 텍스트로 답변 끝 판단 | LiveKit Model License | 무료 | LiveKit Agents 안에서만 | 로컬 | **쓰지 않음**. 라이선스가 LiveKit Agents 밖 사용을 막는다 |
| LiveKit 서버, client-sdk-js, Agents | 비대면 WebRTC 통화 | Apache-2.0 | 무료 (자체 운영) | 가능 | 로컬 (자체 서버) | 후보 (11단계) |
| 브라우저 AEC·NS·AGC (WebRTC 오디오 처리) | 에코 제거, 잡음 억제, 자동 음량 | 브라우저 내장 | 무료 | 가능 | 로컬 (브라우저) | 후보 (11단계) |
| RNNoise | 서버 잡음 억제 | BSD-3-Clause | 무료 | 가능 | 로컬 | 후보, 기본 끔 |
| DeepFilterNet | 서버 잡음 억제 | MIT 또는 Apache-2.0 | 무료 | 가능 | 로컬 | 후보, 기본 끔 |

## 6. 클라우드 서비스: 무엇이 나가고 얼마인가

모두 구현 전이다. 가격은 2026-10-27 공개 정가, 세금 별도.

| 서비스 | 회사 밖으로 나가는 것 | 처리 리전 | 학습에 쓰나 | 과금 단위와 가격 |
| --- | --- | --- | --- | --- |
| Vertex AI의 Claude | 비식별 텍스트 (프롬프트) | global, us, eu. 서울 없음 | 사전 허락 없이 안 씀 (Google) | 100만 토큰당, 4장 |
| Vertex AI 임베딩 | 비식별 답변, 회사가 쓴 질문 | gemini-embedding-001은 서울 가능 | 같음 | "1,000개"당 $0.00015 (단위 확인 필요) |
| Google STT v2 (Chirp 3) | **음성 원본** | us, eu | 로깅은 선택, 기본 꺼짐 | 분당 $0.016 (Chirp 3 적용 확인 필요), [stt.md](stt.md) |
| Google Document AI OCR | **서류 그림 원본** | us·eu GA (아시아 단일 리전은 Preview, 서울 없음) | 확인 필요 | 월 1,000쪽 무료, 그다음 1,000쪽당 $1.50, 500만 쪽 넘으면 $0.60 (표기는 "count") |
| NAVER CLOVA OCR | **서류 그림 원본** | 한국·일본 (가격 화면에는 더 많은 리전, 확인 필요) | 엔진 개선에 쓰지 않고 그림을 저장하지 않는다(FAQ) | 일반 OCR 호출당 3원(표 추출은 22원 추가), 월 100회 무료. 템플릿 OCR은 월정액(Basic 35,000원에 1,000회 …) |
| CLOVA Speech, Azure, AWS, 리턴제로, OpenAI, Deepgram, ElevenLabs | **음성 원본** | 서비스마다 다름 | 서비스마다 다름 (AWS는 기본 허용) | [stt.md](stt.md) 2장 |
| pyannoteAI | **음성 원본** | EU | 확인 필요 | 시간당 €0.096~0.198, [diarization.md](diarization.md) 4장 |

- Google 서비스는 회사 밖(외부 클라우드)이다. 2026-10-21에는 "사내 GCP"(이 PoC를 위해 직접 만들 GCP 프로젝트)로 보고 PoC 기본값으로 삼았으나, 2026-10-28 GCP를 쓰지 않기로 했다([model-selection.md](../model-selection.md) 7장). 관리자 화면도 Google 계열을 회사 밖으로 보고 전송 확인을 받는다. 쓰려면 보안 승인이 먼저다.
- 음성과 서류 그림은 비식별화 전 원본이라 이름·얼굴·목소리가 그대로 나간다. 텍스트(LLM·임베딩)는 비식별화와 가드를 거친 뒤에만 나간다.

## 7. 라이선스 주의

| 종류 | 해당 | 이 프로젝트의 처리 |
| --- | --- | --- |
| AGPL | pyhwp, PyMuPDF | 쓰지 않는다. 네트워크로 서비스하면 소스 공개 의무가 생긴다 |
| 비상업 가중치 (CC BY-NC) | NVIDIA Sortformer v1, DiariZen | 쓰지 않는다 |
| 쓰는 곳을 제한하는 모델 라이선스 | LiveKit turn detector (LiveKit Agents 밖 사용 금지) | 쓰지 않는다 |
| 약관 동의 후 받는 모델 | pyannote 3.1·community-1 (Hugging Face에 계정 정보 공유) | 후보. community-1은 CC-BY-4.0이라 출처를 표시한다 |
| 표기가 엇갈림 | Whisper large-v3: GitHub는 MIT, Hugging Face 카드는 Apache-2.0 | 둘 다 상업 사용 가능 |
| **PyAV 휠에 든 FFmpeg** | 이 PC의 av 19.0.1 휠은 FFmpeg 9.0.2와 함께 `libx264`·`libx265` DLL을 싣는다(`.venv/Lib/site-packages/av.libs/`). x264·x265는 GPL이다. 빌드 스크립트는 `--enable-gpl` 없이 패치로 둘을 GPLv3 계열 목록으로 옮겼다 | **법무 확인 필요.** 우리는 오디오 디코딩만 쓰지만 바이너리를 배포하거나 사내 오픈소스 검토를 받으면 GPL 의무가 걸릴 수 있다. faster-whisper가 PyAV에 의존하므로, 문제가 되면 x264·x265 없이 빌드한 FFmpeg로 PyAV를 만들어야 한다 |
| 폰트 | Pretendard (OFL-1.1) | 웹에 자체 호스팅. 폰트만 따로 팔지 않으면 된다 |
| 별도 프로그램 | LibreOffice (MPL-2.0) | 고치지 않고 명령행으로 실행만 한다 |

## 8. 쓰지 않기로 한 것

| 이름 | 사유 | 자세히 |
| --- | --- | --- |
| pyhwp | AGPL | [document-reading.md](../document-reading.md) "HWP 도구 결정" |
| PyMuPDF | AGPL | [deidentification.md](../deidentification.md) |
| 멀티모달 LLM에 이력서 그림 넣기 | 비식별화를 건너뛴다 | [document-reading.md](../document-reading.md) |
| Tesseract를 기본 OCR로 | 한국어 오류가 크다. 비교용으로만 | [ocr-benchmark.md](../ocr-benchmark.md) |
| PaddleOCR server 검출 (CPU) | 쪽당 30초 이상, 메모리 2.9GB | [ocr-benchmark.md](../ocr-benchmark.md) |
| paddlepaddle 3.3.1 | oneDNN이 Windows CPU에서 실패, oneDNN 없이는 4배 느림 | [document-reading.md](../document-reading.md) |
| FlagEmbedding + torch | torch 1GB 이상, PaddleOCR 때와 같은 Intel OpenMP DLL 충돌 위험 | [model-selection.md](../model-selection.md) 6장 |
| BGE-M3 멀티벡터(ColBERT) 출력 | 질문이 짧아 밀집 + 희소로 충분했다 | [model-selection.md](../model-selection.md) 6장 |
| 모범 답안과의 유사도로 채점, 지난 지원자 답변 임베딩 | 공정성, 목적 외 이용, 편향 전파 | [question-bank.md](../question-bank.md) 1장 |
| Whisper small (실사용) | 한국어 CER 13% | [whisper-benchmark.md](../whisper-benchmark.md) |
| LiveKit turn detector | 라이선스 | [audio-quality.md](audio-quality.md) 6장 |
| NVIDIA Sortformer v1, DiariZen | 비상업 가중치 | [diarization.md](diarization.md) 3장 |
| 목소리 등록으로 사람 알아보기 | 민감정보(생체인식정보), 별도 동의 필요 | [diarization.md](diarization.md) 5장 |
| AWS Transcribe (AI 서비스 거부 정책 없이) | 기본값이 학습 허용 | [stt.md](stt.md) 6장 |
| OpenAI 실시간 전사 | 처리가 미국·EU뿐, 모델 종료 예정 | [stt.md](stt.md) 9장 |

## 출처

확인 날짜 2026-10-27. 설치된 패키지의 라이선스는 이 PC의 `.venv`와 `frontend/node_modules` 메타데이터로 확인했다.

- [Claude on Vertex AI (Anthropic 문서)](https://platform.claude.com/docs/en/build-with-claude/claude-models-on-google-cloud/google-managed), [Claude Opus 5.5 on Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude/opus-5-5)
- [Vertex AI 생성형 AI 가격](https://cloud.google.com/vertex-ai/generative-ai/pricing), [Vertex AI 리전](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations), [Vertex AI 데이터 거버넌스](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance)
- [Vertex AI 텍스트 임베딩](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings), [임베딩 지원 언어](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/text-embeddings-api#supported_text_languages)
- [Document AI 가격](https://cloud.google.com/document-ai/pricing), [Document AI 언어](https://docs.cloud.google.com/document-ai/docs/languages), [Document AI 리전](https://docs.cloud.google.com/document-ai/docs/regions)
- [CLOVA OCR 가격](https://www.ncloud.com/product/aiService/ocr#pricing), [CLOVA OCR 개요](https://guide.ncloud-docs.com/docs/clovaocr-overview), [CLOVA OCR FAQ](https://guide.ncloud-docs.com/docs/clovaocr-faq)
- [OpenAI text-embedding-3-large](https://developers.openai.com/api/docs/models/text-embedding-3-large)
- 라이선스: [PyMuPDF](https://pypi.org/project/pymupdf/), [pyhwp](https://github.com/mete0r/pyhwp), [hwplib](https://github.com/neolord0/hwplib), [syhwp](https://github.com/sysphere/syhwp), [LibreOffice](https://www.libreoffice.org/about-us/licenses/), [Tesseract](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE), [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE), [PP-OCRv5 모델](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec), [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3), [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding), [Pretendard](https://github.com/orioncactus/pretendard/blob/main/LICENSE), [PyAV](https://github.com/PyAV-Org/PyAV/blob/master/LICENSE.txt), [CTranslate2](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE), [ONNX Runtime](https://github.com/microsoft/onnxruntime/blob/main/LICENSE), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [openai/whisper](https://github.com/openai/whisper)
- PyAV의 FFmpeg: [pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg), [빌드 스크립트](https://github.com/PyAV-Org/pyav-ffmpeg/blob/main/scripts/build-ffmpeg.py), [FFmpeg 패치](https://github.com/PyAV-Org/pyav-ffmpeg/blob/main/patches/ffmpeg.patch), [x264](https://www.videolan.org/developers/x264.html), [x265](https://bitbucket.org/multicoreware/x265_git/src/master/COPYING)
- 음성 도구: [Silero VAD 라이선스](https://raw.githubusercontent.com/snakers4/silero-vad/master/LICENSE), [Pipecat Smart Turn](https://github.com/pipecat-ai/smart-turn), [LiveKit turn detector 라이선스](https://huggingface.co/livekit/turn-detector/blob/main/LICENSE), [LiveKit 서버](https://github.com/livekit/livekit), [LiveKit client-sdk-js](https://github.com/livekit/client-sdk-js), [LiveKit Agents](https://github.com/livekit/agents), [RNNoise](https://github.com/xiph/rnnoise), [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)
- 화자분리 모델·STT 서비스의 출처는 [diarization.md](diarization.md), [stt.md](stt.md) 끝에 있다.

### 확인 필요

- Vertex 임베딩 가격의 "1,000개" 단위, text-multilingual-embedding-002의 리전, Vertex 임베딩의 희소 출력 여부
- Vertex 가격 페이지의 지역별 Haiku 5.5 표기(문서는 지역 엔드포인트에 5.x 모델이 없다고 적음)
- Anthropic이 Vertex AI 프롬프트를 볼 수 있는지에 대한 명시(Google 문서는 "모든 관리형 모델"을 학습에 쓰지 않는다고만 적음)
- Document AI의 학습 사용 정책, 가격 단위("count"가 쪽인지)
- CLOVA OCR의 실제 리전 목록, 접근 기록 보관 기간
- PyAV 휠에 든 FFmpeg(x264·x265)의 실제 라이선스 의무 (법무)
- Gemini·사내 LLM 대안의 가격·조건 (조사 안 함). 오픈 웨이트 모델의 확인 필요 항목은 [llm.md](llm.md) 끝
