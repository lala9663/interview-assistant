# LLM 비교: 사내에서 돌릴 오픈 웨이트 모델

2026-10-28 · 한국어 면접 작업(꼬리질문, 서류 선별, 답변 채점, 역량 사전 초안)에 쓸 오픈 웨이트 모델을 비교한다. 앱은 사내에 설치한 모델 서버(vLLM·Ollama·SGLang)의 OpenAI 형식 API에 `open_model_server` provider로 붙는다. 설정법은 [ai-models.md](../ai-models.md), 역할별 기준은 [model-selection.md](../model-selection.md).

전제(2026-10-28 사용자 확인):

- OpenAI 서비스는 쓸 수 없다. GCP(Vertex AI의 Claude 포함)도 쓰지 않는다.
- 오픈소스 모델은 쓸 수 있을 것이다.
- 실행 위치와 GPU 유무는 아직 모른다.

이 문서의 숫자는 모두 공개 자료다. 이 저장소에서 실제 모델로 잰 값은 아직 없다(실제 모델 미확인). 결정은 4장의 방법으로 사내 GPU에서 다시 재서 한다.

## 1. 무엇을 보나

| 기준 | 왜 |
| --- | --- |
| 라이선스 | 사내 업무에 쓰는 것도 "상업적 이용"일 수 있다. 비상업(NC) 라이선스는 연구·교육만 허락하므로 채용 업무에는 별도 계약이 필요하다 |
| 출처 국가·회사 | 사내 정책이 중국 회사 모델(Qwen, DeepSeek)과 그 파생 모델을 막을 수 있다. 한국 회사 모델 중에도 Qwen을 바탕으로 한 것이 있어 따로 적었다 |
| GPU 메모리 | 가중치 크기는 정밀도에 비례한다. BF16 2바이트, FP8·INT8 1바이트, 4비트 0.5바이트. 여기에 KV 캐시(동시 요청 수 × 입력 길이)가 더해진다 |
| 한국어 성능 | KMMLU·KMMLU-Pro·CLIcK·KoBALT·HAE-RAE·Ko-IFEval·KoMT-Bench. 대부분 모델을 낸 회사가 직접 잰 값이고 설정(추론 모드, 프롬프트)이 서로 달라 표끼리 바로 비교하면 안 된다 |
| 첫 토큰 | 꼬리질문은 답변이 끝나자마자 첫 질문이 보여야 한다. 추론(thinking) 모드가 켜져 있으면 답 앞에 생각을 먼저 길게 만들어 첫 토큰이 늦다. 끌 수 있는지가 중요하다 |
| 구조화 출력 | 선별·채점·역량 사전은 JSON으로 받는다. 서버(vLLM·SGLang·Ollama)가 JSON 스키마대로만 생성하게 제약하므로 모델과 거의 무관하다. gpt-oss는 harmony 형식이 필요하다(vLLM이 처리) |
| 도구 호출 | 지금은 쓰지 않는다(범위 밖). 나중에 에이전트 기능을 붙일 때를 위해 적었다 |
| 컨텍스트 | 서류 선별은 공고 + 이력서라 수천~1만 토큰. 32K면 충분하고, 서버 설정(vLLM `--max-model-len`, Ollama `num_ctx`)이 실제 한도다 |

## 2. 한눈에

GPU 1~2장(48~80GB급)에 올라가는 크기를 중심으로 골랐다. 메모리의 "계산"은 파라미터 수 × 바이트(가중치만, KV 캐시 제외), "카드"는 모델 카드, "Ollama"는 Ollama 공식 라이브러리의 내려받기 크기다.

| 모델 | 크기 (전체 / 활성) | 라이선스 (상업 사용) | 출처 | GPU 메모리 BF16 / 8비트 / 4비트 | 한국어 근거 | 도구 호출 | 컨텍스트 | 추론 끄기 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **SKT A.X 3.1** | 34B dense | Apache-2.0 (가능) | 한국 SKT, 처음부터 학습 | 계산 68 / 34 / 17GB | KMMLU 69.73, CLIcK 77.09, Ko-IFEval 75.29, KoMT 83.06 (SKT) | 지원 (vLLM hermes) | 32K (YaRN 131K) | 추론 모드 없음 (카드에 언급 없음) |
| SKT A.X 3.1 Light | 7B dense | Apache-2.0 (가능) | 한국 SKT, 처음부터 학습 | 계산 14 / 7 / 3.5GB | KMMLU 61.70, CLIcK 71.22, KoBALT 27.43, Ko-IFEval 70.04 (SKT) | 확인 필요 | 32K | 추론 모드 없음 (카드에 언급 없음) |
| SKT A.X 4.0 | 72B dense | Apache-2.0 (가능) | 한국 SKT, **Qwen2.5 기반** | 계산 144 / 72 / 36GB | KMMLU 78.32, CLIcK 83.51, KoBALT 47.30, Ko-IFEval 77.96 (SKT) | 지원 | 131K | 추론 모드 없음 (카드에 언급 없음) |
| Kakao Kanana-2 30B-A3B Instruct (2601) | 30B / 3B MoE | Kanana License (조건부: 자체 서비스 운영은 허용, SI·온프레미스 솔루션의 일부·API 재판매·MAU 1천만 초과는 별도 계약) | 한국 카카오 | 계산 62 / 31 / 16GB | KMMLU 68.26, KoMT 8.21, HAE-RAE 75.57 (카카오) | 지원 (vLLM hermes) | 32K (YaRN 128K) | 추론은 별도 모델 (instruct는 없음) |
| NAVER HyperCLOVA X SEED Think 32B | 32B dense (시각 포함) | 조건부 가능 (로열티 없음, MAU 1천만 초과·네이버 경쟁 제품은 별도, "Powered by HyperCLOVA X" 표기) | 한국 네이버, 시각 인코더는 Qwen2.5-VL의 ViT | 카드: GPU 2장 LLM 약 60GB + 시각 약 8GB | KMMLU 71.3, CLIcK 75.2, KoBALT 50.6, HAERAE 87.4 (네이버 기술 보고서) | 확인 필요 | 128K | 기본 꺼짐 |
| NAVER HyperCLOVA X SEED Think 14B | 14.7B dense | 확인 필요 (32B 라이선스만 읽음) | 한국 네이버 | 계산 29 / 15 / 7GB | KMMLU 54.3(비추론)·66.5(추론), HAERAE 85.1·85.4, CLIcK 72.1·72.8 (네이버) | 지원 (hcx-vllm-plugin 필요) | 32K | `skip_reasoning` |
| LG EXAONE 4.5 33B | 33B dense (시각 포함) | **NC: 상업 목적 사용 금지**, 연구·교육만 | 한국 LG | 계산 66 / 33 / 17GB | KMMLU-Pro 67.6, KoBALT 52.1 (추론, LG) | 지원 | 262K | 가능 (`enable_thinking`) |
| LG EXAONE 4.0 32B | 32B dense | **NC: 상업 목적 사용 금지** | 한국 LG | 계산 64 / 32 / 16GB | KMMLU-Pro 60.0·KMMLU-Redux 64.8(비추론), 67.7·72.7(추론) (LG) | 지원 | 131K | 가능 (기본 꺼짐) |
| Qwen3.8-27B | 27B dense (시각 포함) | Apache-2.0 (가능) | **중국 Alibaba** | 계산 54 / 27 / 14GB, Ollama q4 18GB | 공식 한국어 수치 없음. 이전 Qwen3.5 27B는 KMMLU-Pro 73.0, KoBALT 54.9 (LG가 잰 값) | 확인 필요 | 262K | 가능 (기본 켜짐) |
| Qwen3.6-35B-A3B | 35B / 3B MoE | Apache-2.0 (가능) | **중국 Alibaba** | 계산 70 / 35 / 18GB, Ollama q4 24GB | 공식 한국어 수치 없음 | 지원 | 262K | 가능 (기본 켜짐) |
| Gemma 4 31B | 30.7B dense | Apache 2.0 (가능) | 미국 Google | 계산 61 / 31 / 15GB, Ollama q4 20GB | 한국어 수치 없음 (다국어 MMMLU 88.4) | 지원 | 256K | 기본 꺼짐 |
| Gemma 4 26B-A4B | 25.2B / 3.8B MoE | Apache 2.0 (가능) | 미국 Google | 계산 50 / 25 / 13GB, Ollama q4 18GB | 한국어 수치 없음 (MMMLU 86.3) | 지원 | 256K | 기본 꺼짐 |
| Meta Muse Glimmer 30B | 29.6B dense (시각 포함) | Apache 2.0 (가능, 사용 정책 별도) | 미국 Meta | 카드: 원정밀도 64GB, 4비트 20GB 미만 | 한국어 언급·수치 없음 | 지원 | 131K 이상 | 확인 필요 (가장 낮은 단계 low) |
| Mistral Small 4 | 119B / 6.5B MoE | Apache 2.0 (가능) | 프랑스 Mistral | 계산 238 / 119 / 60GB | 공식 한국어 수치 없음 (지원 언어에 한국어 있음) | 지원 | 256K | 가능 (`reasoning_effort: none`) |
| Ministral 3 14B | 14B dense | Apache 2.0 (가능) | 프랑스 Mistral | 카드: FP8 24GB 안, Ollama q4 9.1GB | 수치 없음 (한국어 지원 명시) | 지원 | 256K | 추론은 별도 체크포인트 |
| OpenAI gpt-oss-20b | 21B / 3.6B MoE | Apache 2.0 (가능) · **사내 정책 확인 필요** | 미국 OpenAI | 카드: MXFP4로 16GB 안, Ollama 14GB | MMMLU 한국어 69.8 / 75.7 / 77.6 (추론 low/medium/high, OpenAI). KMMLU-Pro 42.9, CLIcK 57.2 (KO-REAson 논문) | 지원 | 131K | 불가 (가장 낮은 단계 low) |
| OpenAI gpt-oss-120b | 117B / 5.1B MoE | Apache 2.0 (가능) · **사내 정책 확인 필요** | 미국 OpenAI | 카드: 80GB GPU 1장, Ollama 65GB | MMMLU 한국어 75.2 / 80.9 / 82.9 (low/medium/high, OpenAI) | 지원 | 131K | 불가 (가장 낮은 단계 low) |
| DeepSeek V4-Flash | 284B / 13B MoE | MIT (가능) | **중국 DeepSeek** | GPU 1~2장에 안 들어감 (FP4·FP8 혼합 가중치) | KMMLU-Pro 78.8, KoBALT 75.3, CLIcK 89.6 (SKT가 잰 값) | 확인 필요 | 1M | 가능 (Non-think) |

굵은 글씨의 라이선스·출처는 결정 전에 막힐 수 있는 것이다.

## 3. 작업별 권장

공개 자료로 좁힌 후보다. 숫자로 정한 것이 아니므로 4장의 측정으로 확정한다.

지금 앱에서 꼬리질문·AI 채점·역량 사전 초안은 같은 역할(LLM 주 모델)이고, 서류 구조화·선별만 LLM 선별용이다. 그래서 주 모델 하나가 빠른 첫 토큰과 채점 품질을 함께 맡는다. 둘이 부딪히면 꼬리질문 역할을 따로 떼는 것이 다음 할 일이다.

| 작업 | 중요한 것 | 1순위 | 대안 |
| --- | --- | --- | --- |
| 꼬리질문 (실시간, 스트리밍) | 첫 토큰. 추론 모드가 없거나 끌 수 있어야 하고, 출력이 짧아(약 300토큰) 생성 속도도 본다 | **A.X 3.1** (카드에 추론 모드 언급 없음, 한국어 수치 공개, Apache-2.0, 한국 회사가 처음부터 학습) | 더 빨라야 하면 A.X 3.1 Light(7B). 미국 모델이 필요하면 Gemma 4 26B-A4B(추론 기본 꺼짐, 활성 3.8B) |
| 서류 구조화·선별 | 품질과 JSON. 문서가 길고 양이 많다 | **A.X 3.1** (주 모델과 같은 서버) | 품질을 더 올리려면 A.X 4.0 72B(한국어 수치 가장 높음, 단 Qwen2.5 기반이라 중국 모델 정책 확인) 또는 HyperCLOVA X SEED Think 32B(라이선스 조건 확인) |
| 답변 채점 (BARS 1~5, 3회 표본) | 품질과 일관성. 한 답변을 세 번 부르므로 처리량도 본다 | **A.X 3.1** | A.X 4.0 72B, HyperCLOVA X SEED Think 32B(추론 켜면 품질↑, 속도↓) |
| 역량 사전 초안 | 품질. 공고 하나에 한 번이라 느려도 된다 | **A.X 3.1** | 위와 같음. 추론 모드를 켤 수 있는 모델은 이 작업에서만 켜는 것도 방법(지금은 역할 단위 설정이라 따로 못 켬) |

함께 볼 것:

- **중국 모델이 허용되면** Qwen3.8-27B·Qwen3.6-35B-A3B가 최신이고 Apache-2.0이다. 추론을 끄고(`extra_body`에 `{"chat_template_kwargs": {"enable_thinking": false}}`) 비교 후보에 넣는다. 한국어 공식 수치가 없어 반드시 실측한다.
- **gpt-oss**는 OpenAI가 공개한 가중치를 사내 서버에서 돌리는 것이라 OpenAI 서비스를 부르지는 않는다. 그래도 "OpenAI 불가" 정책이 회사(서비스)만 막는지 OpenAI가 만든 모델까지 막는지는 **확인 필요**다. 추론을 끌 수 없어 꼬리질문 첫 토큰에는 불리하다.
- **EXAONE 4.0·4.5는 쓰지 않는다**(비상업 라이선스). LG와 별도 계약을 맺으면 다시 본다.
- **Kanana-2**는 자체 서비스 운영은 허용하지만 "SI 또는 온프레미스 배포 솔루션의 일부"로 제공하면 별도 계약이다. 이 PoC가 사내 납품 형태라면 이 조항에 걸리는지 **법무 확인** 전까지 보류한다.
- **HyperCLOVA X SEED**는 사내 사용에 맞는 조건(로열티 없음)이지만 "Powered by HyperCLOVA X" 표기, 네이버 경쟁 제품 조항이 있다. 32B는 시각 인코더(Qwen2.5-VL ViT)까지 올라가 메모리를 더 쓴다.
- **GPU 크기 감**: A.X 3.1을 FP8로 올리면 가중치 약 34GB에 KV 캐시가 더해져 48GB GPU 1장이 하한, 80GB 1장이면 동시 요청에 여유가 있다(계산, 미측정). A.X 4.0 72B는 FP8로도 80GB 1장에 빠듯해 2장이 현실적이다.
- **이 노트북(i7-1360P, RAM 16GB, GPU 없음)에서 흐름만 시험**하려면 Ollama 공식 라이브러리의 작은 모델을 쓴다: `gemma4:e4b`(6.6GB, Apache 2.0), `qwen3.5:4b`(3.3GB, Apache-2.0, 중국), `ministral-3:3b`(3.0GB, Apache 2.0). 한국 회사 모델(EXAONE, Kanana, A.X, HyperCLOVA X)은 Ollama 공식 항목이 없다(커뮤니티 변환본만). 품질 판단용이 아니라 연결·형식 확인용이다.

## 4. 결정 전에 잴 것

사내 GPU가 정해지면 후보 2~3개를 같은 조건으로 잰다. 측정 스크립트는 아직 없다(다음 할 일).

1. 같은 비식별 샘플: 면접 답변 20개(꼬리질문·채점), 이력서 10개 + 공고(선별), 공고 3개(역량 사전).
2. 꼬리질문: 관리자 화면 연결 테스트의 "첫 토큰" 값과, 실제 꼬리질문 프롬프트의 첫 토큰·전체 시간(동시 면접 수만큼 동시에).
3. JSON 성공률: 스키마 강제(`json_schema`)와 프롬프트만(`prompt`)에서 파싱·검증 실패 비율.
4. 채점: 같은 답변 3회 표본의 점수 흩어짐, 면접관 점수와의 차이.
5. 처리량: 서류 100건 선별에 걸리는 시간.

## 5. 모델별 메모

- **Qwen (Alibaba, 중국)**: 3.5(2026-02~03), 3.6(04), 3.8(08)이 나왔다. 오픈 웨이트는 Apache-2.0. 추론 모드가 기본으로 켜져 있고 요청마다 `enable_thinking: false`로 끈다. Alibaba는 한국어 전용 수치를 내지 않고 다국어 평균(MMMLU 등)만 낸다.
- **Gemma 4 (Google, 미국)**: 2026-04 공개, 12B는 06월 추가. 이전 세대의 Gemma 약관이 아니라 Apache 2.0이다. 추론 모드는 기본 꺼짐(시스템 프롬프트의 `<|think|>`로 켬). 한국어를 따로 언급하지 않는다.
- **Meta**: Llama 5는 Hugging Face meta-llama 조직에서 찾지 못했다. 새 오픈 모델 이름은 Muse다(Glimmer 30B, Apache 2.0, 2026-08). Llama 4(Scout 109B-A17B 등)는 Llama 4 Community License(MAU 7억 초과 시 별도, "Built with Llama" 표기, 파생 모델 이름 조건)이고 지원 언어 목록에 한국어가 없다.
- **Mistral (프랑스)**: Small 4(119B-A6.5B, 2026-03), Ministral 3(3B·8B·14B), Medium 3.5(128B, "Modified MIT", 매출 큰 기업 예외 기준은 확인 필요). 지원 언어에 한국어가 있지만 한국어 수치는 내지 않는다.
- **LG EXAONE (한국)**: 4.0(2025-07)·4.5(2026-04) 모두 "EXAONE AI Model License Agreement 1.2 - NC". 3.1조가 상업 목적 사용을 금지하고, 2.1조는 연구·교육 목적만 허락한다. 한국어 수치는 공개돼 있다.
- **Kakao Kanana-2 (한국)**: 30B-A3B instruct(2026-01)와 3B(2026-07). 추론은 별도 `-thinking` 모델. 라이선스 4.1조(SI·온프레미스·API 재판매·온디바이스는 별도 계약), 4.2조(MAU 1천만), 3.1조("Powered by Kanana" 표기, 파생 모델 이름 앞에 Kanana). HF 아키텍처 태그 `deepseek_v3`는 구조 이름일 뿐 가중치 출처가 아니다.
- **SKT A.X (한국)**: 3.1·3.1 Light(2025-07-24)는 처음부터 학습, 4.0·4.0 Light(2025-07-03)는 Qwen2.5 기반. 모두 Apache-2.0. 추론 모드는 카드에 언급이 없다.
- **NAVER HyperCLOVA X SEED (한국)**: Think 32B(2025-12, 시각 포함), Think 14B, Omni 8B. 32B 라이선스는 로열티 없는 사용을 허락하되 MAU 1천만 초과·네이버 경쟁 제품은 네이버 허락이 필요하다. 공식 서빙은 OmniServe, vLLM에도 등록돼 있다.
- **OpenAI gpt-oss (미국)**: 20b·120b(2025-08), Apache 2.0, 사용 정책은 "관련 법 준수" 수준. 추론 low/medium/high를 시스템 프롬프트로 고르고 끄는 선택지는 없다. harmony 응답 형식 필수.
- **DeepSeek (중국)**: V4-Flash(2026-04, 284B-A13B, MIT), V4.1-Flash. GPU 1~2장에는 안 들어간다.

## 6. 국가 프로젝트(독자 AI 파운데이션 모델)

2026-08-18 2차 평가에서 업스테이지, SKT, LG가 통과했다. 모두 GPU 여러 장(노드 단위)이 필요하고 각 회사가 고친 vLLM이 필요해 이 PoC의 1~2장 구성에는 맞지 않는다.

| 모델 | 크기 | 라이선스 | 한국어 근거 | 하드웨어 |
| --- | --- | --- | --- | --- |
| LG K-EXAONE 2.0 | 750B-A37B | Apache 2.0 | KMMLU-Pro 69.1, CLIcK 84.2 | H200 8장 × 2노드 예시 |
| SKT A.X K2 | 688B-A33B, 처음부터 학습 | Apache-2.0 (메타데이터) | KMMLU-Pro 80.5, KoBALT 73.0, CLIcK 91.6 | GPU 메모리 800GiB 이상 |
| Upstage Solar Open 2 | 250B-A15B | Solar License (파생 모델 이름 "Solar", "Built with Solar" 표기) | KMMLU-Pro 78.4, CLIcK 90.7 | H200 4장 이상 |
| Upstage Solar Open 100B | 102.6B-A12B | 확인 필요 | KMMLU 73.0, KMMLU-Pro 64.0, KoBALT 44.3 | A100 80GB 4장 이상 |

## 출처

확인 날짜 2026-10-28. 모델 카드·라이선스 파일·기술 보고서를 직접 읽었다. A.X 3.1, A.X 4.0 Light, EXAONE 4.0 32B·4.5 라이선스, Kanana-2 30B 카드·라이선스, HyperCLOVA X SEED Think 32B 라이선스, Gemma 4 31B, Qwen3.8-27B, Muse Glimmer 30B, gpt-oss-20b, gpt-oss 기술 보고서의 한국어 MMMLU는 두 번 확인했다.

- Qwen: [Qwen3.8 저장소](https://github.com/QwenLM/Qwen3.8), [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B), [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B), [Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B), [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), Ollama [qwen3.8](https://ollama.com/library/qwen3.8/tags) · [qwen3.6](https://ollama.com/library/qwen3.6/tags) · [qwen3.5](https://ollama.com/library/qwen3.5/tags)
- Gemma 4: [gemma-4-31B-it](https://huggingface.co/google/gemma-4-31B-it), [Google 블로그](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/), [릴리스](https://ai.google.dev/gemma/docs/releases), [Ollama gemma4](https://ollama.com/library/gemma4/tags)
- Meta: [Muse-Glimmer-30B](https://huggingface.co/meta-models/Muse-Glimmer-30B), [HF 블로그](https://huggingface.co/blog/muse-glimmer), [Artificial Analysis](https://artificialanalysis.ai/articles/muse-glimmer), [Ollama muse-glimmer](https://ollama.com/library/muse-glimmer/tags), [meta-llama 조직](https://huggingface.co/meta-llama), [Llama-4-Scout](https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct)
- Mistral: [Mistral-Small-4-119B-2603](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603), [Mistral Small 4 발표](https://mistral.ai/news/mistral-small-4/), [Ministral-3-14B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512), [Ollama ministral-3](https://ollama.com/library/ministral-3/tags), [Mistral-Medium-3.5-128B](https://huggingface.co/mistralai/Mistral-Medium-3.5-128B)
- OpenAI: [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b), [gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) (USAGE_POLICY), [gpt-oss 모델 카드 논문 (언어별 MMMLU)](https://arxiv.org/html/2508.10925), [Ollama gpt-oss](https://ollama.com/library/gpt-oss/tags), [KO-REAson 논문](https://arxiv.org/html/2510.04230)
- LG: [EXAONE-4.5-33B](https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B), [EXAONE 4.5 라이선스](https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B/blob/main/LICENSE), [EXAONE-4.0-32B](https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-32B), [EXAONE-4.0-1.2B](https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-1.2B), [K-EXAONE-2.0](https://huggingface.co/LGAI-EXAONE/K-EXAONE-2.0-750B-A37B)
- Kakao: [kanana-2-30b-a3b-instruct-2601](https://huggingface.co/kakaocorp/kanana-2-30b-a3b-instruct-2601), [Kanana 라이선스](https://huggingface.co/kakaocorp/kanana-2-30b-a3b-instruct-2601/blob/main/LICENSE), [kanana-2-3b-instruct](https://huggingface.co/kakaocorp/kanana-2-3b-instruct), [카카오 발표](https://www.kakaocorp.com/page/detail/11912?lang=ENG)
- SKT: [A.X-3.1](https://huggingface.co/skt/A.X-3.1), [A.X-3.1-Light](https://huggingface.co/skt/A.X-3.1-Light), [A.X-4.0-Light (A.X 4.0 표 포함)](https://huggingface.co/skt/A.X-4.0-Light), [A.X-K2](https://huggingface.co/skt/A.X-K2)
- NAVER: [HyperCLOVAX-SEED-Think-32B](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Think-32B), [32B 라이선스](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Think-32B/blob/main/LICENSE), [기술 보고서](https://arxiv.org/html/2601.03286), [Think-14B](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Think-14B), [Omni-8B](https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B)
- DeepSeek: [DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash), [공개일](https://simonwillison.net/2026/apr/24/deepseek-v4), [DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash)
- Upstage: [Solar-Open2-250B](https://huggingface.co/upstage/Solar-Open2-250B), [Solar-Open-100B](https://huggingface.co/upstage/Solar-Open-100B)
- [vLLM 지원 모델 목록](https://docs.vllm.ai/en/latest/models/supported_models.html), [독자 AI 파운데이션 모델 2차 평가 기사](https://www.mt.co.kr/article/2026081812375747016)
- Ollama 검색: [exaone](https://ollama.com/search?q=exaone), [kanana](https://ollama.com/search?q=kanana), [a.x](https://ollama.com/search?q=a.x), [hyperclova](https://ollama.com/search?q=hyperclova)

### 확인 필요

- 회사 정책: gpt-oss(OpenAI가 공개한 모델을 사내에서 실행)가 "OpenAI 불가"에 해당하는지, 중국 회사 모델과 그 파생(A.X 4.0의 Qwen2.5 기반, HyperCLOVA X SEED 32B의 Qwen2.5-VL 시각 인코더)을 막는지
- 법무: 채용 업무 사용이 EXAONE NC 라이선스의 "상업 목적"인지(별도 계약 여부), Kanana 라이선스 4.1조 "SI·온프레미스 솔루션"에 이 PoC가 해당하는지
- 한국어 공식 수치가 없는 모델: Qwen3.6·3.8, Gemma 4 전 크기, Muse Glimmer, Mistral Small 4·Medium 3.5, Ministral 3, gpt-oss-120b(MMMLU 한국어 외)
- 도구 호출: Qwen3.8-27B, A.X 3.1 Light, HyperCLOVA X SEED Think 32B, DeepSeek V4. Muse Glimmer의 추론 완전 끄기
- 라이선스 전문: HyperCLOVA X SEED Think 14B·Omni 8B, Solar Open 100B·Solar Open 2의 상용 조건, Mistral Medium 3.5의 매출 기준, Mistral Large 4 가중치 공개 여부, Muse Spark Open(2차 자료만)
- EXAONE 4.5의 vLLM 최소 버전(카드의 "0.5.8"은 오기로 보임), Kanana-2 공식 GGUF 유무, 모티프·NC AI의 오픈 웨이트 현황
- Llama 5가 없다는 판단은 meta-llama 조직에 없다는 사실에 근거한다(Meta 공식 자료 아님)
- 한국어 종합 리더보드(Horangi 등) 점수는 페이지가 위젯이라 읽지 못했다
- 모든 모델의 첫 토큰·처리량은 미측정이다(이 저장소에서 실제 모델로 돌린 적 없음)
