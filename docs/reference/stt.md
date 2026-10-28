# STT 비교

2026-10-27 · 한국어 면접 전사에 쓸 수 있는 STT 선택지. 역할별 기준과 PoC 조합은 [model-selection.md](../model-selection.md) 1·3·5장, 이 PC에서 잰 Whisper 값은 [whisper-benchmark.md](../whisper-benchmark.md), 앞단(마이크·VAD·답변 끝)은 [audio-quality.md](audio-quality.md).

## 1. 무엇을 보나

| 기준 | 왜 |
| --- | --- |
| 한국어 정확도 | 꼬리질문·채점·비식별화가 모두 전사를 읽는다([audio-quality.md](audio-quality.md) 9장). 전문 용어·약어가 많다 |
| 스트리밍 | 실시간 역할은 말하는 도중 부분 전사가 나와야 한다. Whisper는 원래 스트리밍 모델이 아니다 |
| 지연 | 발화 끝 → 확정 전사. 11단계 완료 기준은 부분 전사 0.5초 이하 |
| 사내 설치 | 회사 서버(온프레미스)에서 돌릴 수 있나 |
| 데이터 | 음성 원본이 회사 밖으로 나가나, 어느 리전에서 처리하나, 업체가 학습에 쓰나. 원칙은 "음성 원본은 승인된 원본 영역 밖으로 보내지 않는다" |
| 가격 | 면접 1시간당 비용. 실시간 + 사후를 둘 다 클라우드로 하면 두 번 낸다 |
| 화자분리 내장 | 대면 마이크 하나일 때 필요([diarization.md](diarization.md)) |
| 용어 힌트 | 직군 용어를 미리 알려 그 표기로 받아 적게 하는 기능 |

## 2. 한눈에

가격은 2026-10-27 공개 정가, 세금 별도. 1시간 값은 분당 가격 × 60으로 계산했다.

| 선택지 | 한국어 | 스트리밍 | 사내 설치 | 음성이 가는 곳 | 학습에 쓰나 | 1시간 가격 | 화자분리 | 용어 힌트 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 로컬 Whisper (faster-whisper) | 이 PC에서 medium 이상 CER 0~1.2% (낭독) | 원래 없음. 발화 단위로 잘라 흉내 | 가능 | 회사 안 | 아니오 | 무료 (장비 비용) | 없음 (따로) | `initial_prompt`·`hotwords` |
| Google STT v2 Chirp 3 | ko-KR GA | 가능 | 에어갭 GDC에 한국어 STT 목록 있음, 조건 확인 필요 | Google, 리전 us·eu뿐 | 기본 아니오 (로깅은 선택, V2 적용 확인 필요) | 표준 $0.96, 동적 배치 $0.18 (Chirp 3 적용 확인 필요) | 파일 전사에서 GA, 스트리밍 안 됨 | 문구 1,000개까지 GA |
| Azure AI Speech | ko-KR 실시간·배치·빠른 전사 | 가능 | 컨테이너 (연결형은 과금용 연결 필요, 비연결형은 승인·연간 약정) | Microsoft, Korea Central 가능 | 실시간·빠른 전사는 보관 안 함. 학습 명시는 확인 필요 | 실시간 $1.00, 배치 $0.18, 빠른 전사 $0.36 (Korea Central) | 실시간 GA (한 채널, 최대 35명). 한국어 실시간 확인 필요 | 문구 목록, Custom Speech |
| AWS Transcribe | ko-KR 배치·스트리밍 | 가능 (서울 리전) | 확인 필요 | AWS, 서울 가능 | **조직 정책으로 거부하지 않으면 쓸 수 있음** | 스트리밍 약 $0.60, 배치 $0.36 | 배치·스트리밍, 최대 30명 (한국어 명시는 확인 필요) | 사용자 어휘 |
| NAVER CLOVA Speech | ko 기본 | gRPC (Basic 장문 플랜만) | 확인 필요 | 네이버 클라우드, 한국 | 확인 필요 | 약 1,200원 (예시에서 계산, 화자 인식·스트리밍 단가 확인 필요) | 파일 인식만 | 키워드 부스팅 |
| 리턴제로 (RTZR) | sommers_ko | gRPC·WebSocket | 구축형 공급 (조건 확인 필요) | 리턴제로 (처리 위치 확인 필요) | 확인 필요. 결과는 3일 보관 | 1,000원 (1,000시간까지), 배치·스트리밍 같음 | 파일 전사만 (스트리밍 확인 필요) | 키워드 100개 (스트리밍) |
| OpenAI 전사 API | 모델별 공개 한국어 수치 없음 | gpt-live-transcribe | 공개 안내 없음 | OpenAI. 한국 지역은 저장만, 처리는 미국·EU | 기본 아니오. 남용 감시 30일 (ZDR 가능) | gpt-4o-transcribe $0.36, mini $0.18, 실시간 약 $1.02 | 파일 전용 모델 (실시간 안 됨) | 프롬프트·키워드 |

## 3. 로컬 Whisper (faster-whisper)

이 프로젝트의 `faster_whisper` provider. 이 노트북(i7-1360P, GPU 없음, CPU int8)에서 잰 값이다. FLEURS 한국어 낭독 3클립(62.7초)이라 실제 면접보다 쉽다.

| 크기 | 파일 | 메모리 | 사후 CER | 사후 속도 (실시간 대비) | 스트리밍: 발화 끝 → 확정 (평균) | 스트리밍 CER |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small | 486MB | 0.7GB | 13.0% | 2.9~6.0배 | 3.5~5.7초 | 13.4% |
| medium | 1.5GB | 1.8GB | 1.2% | 1.4~2.1배 | 7.7~8.9초 | 5.4% |
| large-v3-turbo | 1.6GB | 1.9GB | 0.4% | 1.1~1.4배 | 11.5~18.7초 | 0.8% |
| large-v3 | 3.1GB | 3.3GB | 0.0% | 0.8배 | 20초 | 0.4% |

출처: [whisper-benchmark.md](../whisper-benchmark.md). 실시간 대비 = 음성 길이 ÷ 처리 시간.

| | 내용 |
| --- | --- |
| 장점 | 무료, 음성이 회사 밖으로 나가지 않는다, 지금 바로 된다(관리자 화면에서 다운로드·테스트·적용). medium 이상은 한국어 낭독을 거의 그대로 받아 적는다 |
| 단점 | 스트리밍 모델이 아니다. 호출마다 30초 창을 통째로 인코딩해 CPU에서는 발화 끝 뒤 수 초~20초 늦다. 화자분리가 없다. 침묵에서 말을 지어낼 수 있다([audio-quality.md](audio-quality.md) 8장) |
| 모델 | large-v3 1,550M 파라미터. turbo는 large-v3의 디코더를 32층에서 4층으로 줄인 809M 모델로, 품질이 조금 떨어지는 대신 빠르다(번역은 학습하지 않음) |
| 공개 한국어 수치 | Whisper 논문의 FLEURS 한국어 WER(단어 단위): large-v2 14.3%, medium 16.4%, small 19.6%. 논문은 한국어를 학습 데이터 양에 비해 성능이 낮은 언어로 꼽았다. large-v3·turbo의 한국어 수치는 공개 표가 없다(확인 필요). 이 저장소 CER과는 단위가 달라 비교하지 않는다 |
| GPU | faster-whisper README: large-v2, 13분 음성, RTX 3070 Ti에서 openai-whisper 2분 23초 → faster-whisper fp16 1분 3초, int8 59초, 배치 8 17초. 이 저장소에서는 GPU를 재지 못했다 |
| 스트리밍 흉내 | 이 프로젝트는 VAD로 발화를 잘라 끝날 때마다 전사한다. 공개 도구로 whisper_streaming(MIT, 논문 지연 3.3초, 후속 SimulStreaming)과 WhisperLive(MIT, WebSocket 서버)가 있다 |
| 용어 힌트 | `initial_prompt`(이 provider는 30초 창마다 `hotwords`로 넣는다). 요리 문장 샘플에서는 효과가 없었다. 실제 면접 용어로 다시 잰다 |
| 라이선스 | faster-whisper MIT, Whisper 코드·가중치 MIT(GitHub README). Hugging Face의 large-v3 카드 메타데이터는 Apache-2.0으로 적혀 있다. 둘 다 상업 사용 가능 |

## 4. Google Cloud Speech-to-Text v2 (Chirp 3)

외부 클라우드(Google) 대안이다. 2026-10-21 "PoC는 GCP" 결정에 따라 설정 파일 기본값이 됐으나(`google_stt_v2`, 구현 전, 10·11단계), 2026-10-28 GCP를 철회하며 `config/providers.yaml`의 STT 기본값은 로컬 Whisper로 바꿨다. 화자분리 기본값에서도 2026-10-29 뺐다(지금 기본값은 `fake`).

| | 내용 |
| --- | --- |
| 한국어 | ko-KR GA. 스트리밍(StreamingRecognize), 동기(Recognize), 배치(BatchRecognize)가 같은 언어 목록을 쓴다 |
| 스트리밍 | 가능. 중간 결과, 말 시작·끝 이벤트, 끝 판정 민감도([audio-quality.md](audio-quality.md) 6장) |
| 화자분리 | GA, 한국어 포함. 문서에 "BatchRecognize와 Recognize"와 "BatchRecognize만"이 함께 적혀 있다. 어느 쪽이든 **스트리밍은 안 된다**. [model-selection.md](../model-selection.md)는 2026-10-26에 Preview로 적었다가 2026-10-28 GA로 고쳤다(2026-10-22 갱신 문서 기준) |
| 용어 힌트 | 음성 적응(biasing) GA, 문구 1,000개까지. 사용자 프롬프트는 Preview |
| 리전 | Chirp 3는 us·eu 멀티 리전뿐, 아시아 없음. Chirp 2는 asia-southeast1(싱가포르)에 Private GA |
| 데이터 | 회사 밖(Google)이고, 음성은 미국이나 EU에서 처리된다. 로깅은 기본 꺼짐이고, 켜면 서비스 개선에 쓰인다(V1 문서 기준, V2 적용은 확인 필요) |
| 가격 | V2 표준: 월 50만 분까지 분당 $0.016(1시간 $0.96), 더 쓰면 $0.010 → $0.008 → $0.004. 동적 배치 분당 $0.003(1시간 $0.18). 1초 단위 과금. 가격표가 chirp_3를 따로 적지 않아 같은 값인지 확인 필요 |
| 사내 설치 | Google Distributed Cloud 에어갭에 Speech-to-Text가 있고 언어 목록에 ko-KR이 있다. 모델·스트리밍·가격·하드웨어는 확인 필요 |
| 장점 | 진짜 스트리밍이라 지연이 짧을 것이다(미측정). 배치에서 화자분리를 같이 받는다 |
| 단점 | 음성이 회사 밖, 그것도 해외 리전으로 간다. 스트리밍 화자분리가 없다 |

## 5. Azure AI Speech

| | 내용 |
| --- | --- |
| 한국어 | ko-KR 실시간·배치·빠른 전사(fast transcription). Custom Speech(음성+정답, 텍스트, 문구 목록)도 한국어 지원 |
| 스트리밍 | 가능 |
| 화자분리 | 실시간 화자분리 GA(2024-04, `ConversationTranscriber`, 한 채널, 최대 35명). 다채널 대화 전사는 2025-03-28에 종료. 한국어 실시간 화자분리 지원 목록은 못 찾음(확인 필요) |
| 용어 힌트 | 문구 목록(phrase list), Custom Speech |
| 리전 | Korea Central에서 실시간·빠른 전사·배치·Custom Speech 학습 가능. Azure의 Whisper 모델은 Korea Central에 없다 |
| 데이터 | 실시간·빠른 전사는 Microsoft가 데이터를 보관하지 않는다고 적는다. STT 데이터를 학습에 쓰지 않는다는 명시 문구는 못 찾음(확인 필요) |
| 사내 설치 | STT 컨테이너 GA(한국어 이미지 있음, 실시간 화자분리는 5.1.0부터). 연결형은 음성을 클라우드로 보내지 않지만 과금 때문에 Azure에 연결되어 있어야 한다. 비연결형은 신청·승인(전략 고객·파트너 대상)과 연간 약정이 필요하다(1만 시간 약정 연 $74,100) |
| 가격 (Korea Central, Azure 가격 API) | 실시간 시간당 $1.00, 배치 $0.18, 빠른 전사 $0.36(2026-09부터 $0.10 프로모션 항목이 있음, 조건 확인 필요), 부가 기능 시간당 $0.30(화자분리 요금인지 확인 필요), Custom Speech 실시간 $1.20 |
| 장점 | 한국 리전, 실시간 화자분리, 회사 서버에 컨테이너로 설치 가능 |
| 단점 | 회사에 Azure 계약이 있어야 한다. 컨테이너도 연결형은 과금 연결이 필요하다 |

## 6. AWS Transcribe

| | 내용 |
| --- | --- |
| 한국어 | ko-KR 배치·스트리밍. 한국어는 사용자 언어 모델과 개인정보 가림(redaction)이 안 된다 |
| 스트리밍 | 가능, 서울 리전(ap-northeast-2) 엔드포인트 있음 |
| 화자분리 | 배치·스트리밍 모두, 최대 30명. 기능 표에 언어 제한 표시가 없지만 한국어 명시는 못 찾음(확인 필요) |
| 용어 힌트 | 사용자 어휘(custom vocabulary), 모든 언어 |
| 데이터 | **AWS AI 서비스는 고객 콘텐츠를 서비스 개선·모델 학습에 쓰고 다른 리전에 저장할 수 있다. 막으려면 AWS Organizations의 AI 서비스 거부 정책을 걸어야 한다.** Transcribe가 그 대상이다 |
| 가격 | 서울·미국 같음, 1초 단위. 배치 초당 $0.0001(1시간 $0.36), 스트리밍 초당 $0.0001667(1시간 약 $0.60) |
| 장점 | 서울 리전, 스트리밍 화자분리, 싸다 |
| 단점 | 기본값이 학습 허용이라 계정 정책 확인이 먼저다. 사내 설치 선택지는 확인 필요 |

## 7. NAVER CLOVA Speech

| | 내용 |
| --- | --- |
| 한국어 | 기본 언어. 단문·장문(파일)·실시간 스트리밍 |
| 스트리밍 | gRPC, 16kHz 모노 PCM(이 프로젝트 형식과 같음). Free 플랜에는 없고 Basic 장문 인식 플랜에서만. 끝 신호(`epFlag`)를 보내지 않으면 최대 10초 모아 확정한다([model-selection.md](../model-selection.md) 3장) |
| 화자분리 | 장문(파일) 인식에서만, 기본 켜짐, 화자 수 범위 지정. 실시간 스트리밍은 안 된다 |
| 용어 힌트 | 키워드 부스팅(스트리밍 가중치 0~5, 파일 1,000개까지·500개 이하 권장) |
| 리전 | 한국 |
| 가격 | 15초 단위 올림, 월 20분 무료. 가격 페이지 예시(10초 5원, 32초 15원)로 계산하면 15초당 5원, 1시간 약 1,200원. 화자 인식·스트리밍 단가는 화면에서 스크립트로만 보여 확인 필요 |
| 데이터·사내 설치 | 확인 필요 |
| 장점 | 한국 회사·한국 리전, 입력 형식이 같다 |
| 단점 | 음성이 회사 밖으로 나간다. 스트리밍 화자분리가 없다 |

## 8. 리턴제로 (RTZR)

| | 내용 |
| --- | --- |
| 모델 | 배치 `sommers`(기본)·`whisper`, 스트리밍 `sommers_ko`·`sommers_ja`·`whisper` |
| 스트리밍 | gRPC, WebSocket |
| 화자분리 | 파일 전사에 `use_diarization`(기본 꺼짐), 화자 수 지정·자동. 파일 2GB·4시간까지. 스트리밍 화자분리는 문서에 없음(확인 필요) |
| 용어 힌트 | 키워드 부스팅: 스트리밍은 `sommers_ko`(또는 한국어 whisper)에서 100개, 20자 이하, 점수 -5~5, 한글 발음으로 적는다. 파일은 개수 제한 미기재 |
| 가격 (부가세 별도) | 시간당 1,000원(1,000시간까지) → 500원 → 400원 → 300원. 배치·스트리밍 같은 값, 파일·세션당 최소 10초, 600분 무료 |
| 데이터 | 일반 STT 결과는 3일만 보관. 음성을 학습에 쓰는지는 확인 필요 |
| 사내 설치 | 문서에 구축형(On-Premise) 공급 언급, 도입 문의는 영업으로. 조건 확인 필요 |
| 장점 | 한국어 전용 모델, 구축형 선택지, 싸다 |
| 단점 | 클라우드 API는 음성이 회사 밖으로 나간다. 데이터 정책을 더 확인해야 한다 |

## 9. OpenAI 전사 API

| | 내용 |
| --- | --- |
| 모델·가격 (분당) | gpt-transcribe $0.0045, gpt-4o-transcribe $0.006, gpt-4o-mini-transcribe $0.003, gpt-4o-transcribe-diarize $0.006, whisper $0.006, 실시간 gpt-live-transcribe·gpt-realtime-whisper $0.017. 지역 엔드포인트는 2026-03-05 이후 모델에 10% 추가 |
| 수명 | whisper-1, gpt-4o-transcribe, gpt-4o-mini-transcribe, gpt-4o-transcribe-diarize는 2027-02-26 종료 예정 |
| 스트리밍 | 실시간 전사는 gpt-live-transcribe 권장. 화자 표시 없음, 말 구간은 클라이언트 VAD |
| 화자분리 | gpt-4o-transcribe-diarize, 파일 전용(실시간 세션 안 됨), 프롬프트 없음. 미리 준 목소리 4개까지(목소리 등록이라 쓰지 않음, [diarization.md](diarization.md) 5장) |
| 용어 힌트 | gpt-transcribe·gpt-live-transcribe는 프롬프트·키워드, whisper-1 프롬프트는 224토큰까지 |
| 데이터 | API 데이터는 기본으로 학습에 쓰지 않는다. 남용 감시 로그 30일까지, 무보관(ZDR) 신청 가능. 한국 데이터 거주(kr.api.openai.com)는 저장만 한국이고 전사 처리는 미국·EU에서만, 실시간 전사는 미국·EU뿐 |
| 장점 | 싸고 프롬프트 지원이 좋다 |
| 단점 | 음성이 해외에서 처리된다. 사내 설치 안내가 없다. 모델 교체 주기가 짧다 |

## 10. 그 밖

| 선택지 | 내용 |
| --- | --- |
| Deepgram Nova-3 | 한국어(ko, ko-KR) 지원. 단일 언어 스트리밍 분당 $0.0048·파일 $0.0043, 다국어 $0.0058·$0.0052. 화자분리는 스트리밍 분당 $0.0020 추가(파일은 포함), 용어 힌트(keyterm) $0.0013 추가. 스트리밍·파일 각각의 한국어 지원은 확인 필요 |
| ElevenLabs Scribe v2 | 업체 표에서 한국어는 "WER 10~20%" 등급. 화자분리 32명, 용어 힌트 배치 1,000개·실시간 50개. 배치 시간당 $0.22, 실시간 $0.39 |

둘 다 외부 서비스라 같은 보안 승인이 필요하다.

## 11. 이 프로젝트 기준 권장

| 역할 | 권장 | 이유 |
| --- | --- | --- |
| STT 사후 | **로컬 Whisper large-v3** (지금 설정 가능). 외부 클라우드가 승인되면 그 배치 STT(Chirp 3 등)와 같은 녹음으로 비교 | 이 PC 샘플 CER 0%, 무료, 음성이 회사 밖으로 나가지 않는다. 1시간 녹음에 약 1시간 10분이라 배치로 충분하다. 빨리 받아야 하면 turbo |
| STT 실시간, GPU 서버가 있을 때 | **로컬 Whisper medium·turbo를 GPU로** | 보안상 가장 좋다. GPU 속도는 재야 한다. 스트리밍 흉내 방식이라 0.5초 부분 전사는 장담 못 한다 |
| STT 실시간, 승인된 외부 클라우드가 있을 때 | **그 클라우드의 스트리밍 STT**. Google이면 Chirp 3, Azure 계약이 있으면 Azure(한국 리전·컨테이너 선택지) | 진짜 스트리밍이다. Chirp 3는 us·eu 처리라 리전 요건부터 확인한다 |
| STT 실시간, 둘 다 없을 때 | 로컬 Whisper medium on CPU, 확정까지 8초 이상 감수 | small은 한국어 오류가 커서(13%) 꼬리질문 품질을 망친다 |
| 국내 업체 | 리턴제로 구축형은 회사 서버에 둘 수 있으면 비교 후보. CLOVA·리턴제로 클라우드는 보안 승인 뒤 | 한국어 특화. 공개 한국어 정확도 수치가 없어 같은 녹음으로 재야 한다 |
| 피할 것 | AWS는 계정에 AI 서비스 거부 정책이 없으면 쓰지 않는다. OpenAI는 실시간 처리가 해외뿐이고 모델 종료가 예정되어 PoC 후보에서 뺀다 | 학습 사용 기본값, 데이터 거주 |

공통: 어떤 서비스든 한국어 공개 정확도 수치가 거의 없다. 동의 받은 실제 면접 녹음 몇 건에 정답 전사를 달아 `scripts/bench_whisper.py`처럼 같은 조건(CER, 용어 오류, 발화 끝 → 확정 지연)으로 재서 정한다([audio-quality.md](audio-quality.md) 10장). 회사 밖 서비스는 관리자 화면의 "외부" 경고·사유 단계 전에 보안 승인이 필요하다.

## 출처

확인 날짜 2026-10-27.

- [faster-whisper (GPU 속도표)](https://github.com/SYSTRAN/faster-whisper), [openai/whisper (라이선스, 모델 크기, 30초 창)](https://github.com/openai/whisper)
- [whisper-large-v3-turbo 모델 카드](https://huggingface.co/openai/whisper-large-v3-turbo), [whisper-large-v3 모델 카드](https://huggingface.co/openai/whisper-large-v3)
- Radford 외, [Robust Speech Recognition via Large-Scale Weak Supervision (Whisper 논문, FLEURS 한국어 WER은 부록 D.2.4 표 13)](https://arxiv.org/abs/2212.04356)
- [whisper_streaming](https://github.com/ufal/whisper_streaming), [WhisperLive](https://github.com/collabora/WhisperLive)
- [Chirp 3 (Speech-to-Text v2, 2026-10-22 갱신)](https://docs.cloud.google.com/speech-to-text/v2/docs/chirp_3-model), [Chirp 2](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2), [Speech-to-Text 가격](https://cloud.google.com/speech-to-text/pricing), [데이터 로깅](https://docs.cloud.google.com/speech-to-text/docs/data-logging), [GDC 에어갭 STT 언어](https://docs.cloud.google.com/distributed-cloud/hosted/docs/latest/gdcag/application/ao-user/vertex-ai-stt-supported-langs)
- [Azure 언어 지원](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=stt), [Azure 릴리스 노트](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/releasenotes), [Azure STT 개요](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-to-text), [Azure 리전](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions), [Azure 컨테이너](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-container-overview), [비연결 컨테이너](https://learn.microsoft.com/en-us/azure/ai-services/containers/disconnected-containers), [Azure STT 데이터·개인정보](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security), [Azure 가격 API](https://prices.azure.com/api/retail/prices) (armRegionName koreacentral)
- [AWS Transcribe 지원 언어](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html), [화자분리](https://docs.aws.amazon.com/transcribe/latest/dg/diarization.html), [기능 표](https://docs.aws.amazon.com/transcribe/latest/dg/feature-matrix.html), [사용자 어휘](https://docs.aws.amazon.com/transcribe/latest/dg/custom-vocabulary.html), [엔드포인트](https://docs.aws.amazon.com/general/latest/gr/transcribe.html), [가격](https://aws.amazon.com/transcribe/pricing/), [AI 서비스 거부 정책](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out.html)
- [CLOVA Speech 개요](https://guide.ncloud-docs.com/docs/clovaspeech-overview), [gRPC 스트리밍](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-grpc), [장문 인식](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence), [가격](https://www.ncloud.com/product/aiService/clovaSpeech)
- [리턴제로 개발자 문서](https://developers.rtzr.ai/docs/), [스트리밍](https://developers.rtzr.ai/docs/stt-streaming/), [파일 전사](https://developers.rtzr.ai/docs/stt-file/), [가격](https://developers.rtzr.ai/docs/pricing/)
- [OpenAI 가격](https://developers.openai.com/api/docs/pricing), [전사 안내](https://developers.openai.com/api/docs/guides/speech-to-text), [실시간 전사](https://developers.openai.com/api/docs/guides/realtime-transcription), [데이터 처리](https://developers.openai.com/api/docs/guides/your-data)
- [Deepgram 모델·언어](https://developers.deepgram.com/docs/models-languages-overview), [Deepgram 가격](https://deepgram.com/pricing)
- [ElevenLabs STT](https://elevenlabs.io/docs/overview/capabilities/speech-to-text), [ElevenLabs 가격](https://elevenlabs.io/pricing/api)

### 확인 필요

- Whisper large-v3·turbo의 공개 한국어 CER·WER, large-v3 가중치 라이선스 표기(GitHub MIT vs Hugging Face 카드 Apache-2.0)
- Chirp 3가 V2 표준 가격으로 과금되는지, 데이터 로깅 선택·할인이 V2에도 적용되는지, 동기 Recognize의 화자분리, GDC 에어갭 STT의 모델·스트리밍·가격
- Azure 한국어 실시간 화자분리, 부가 기능 $0.30이 화자분리 요금인지, 빠른 전사 프로모션 조건, STT 데이터를 학습에 쓰지 않는다는 명시
- AWS 화자분리의 한국어 명시, 사내 설치 선택지
- CLOVA 화자 인식·스트리밍 단가, 데이터 사용 정책, 사내 설치
- 리턴제로 스트리밍 화자분리, 파일 키워드 한도, 학습 사용 여부, 구축형 조건, 처리 리전
- Deepgram 한국어의 스트리밍·파일별 지원
- 모든 서비스의 실제 지연(공식 수치 없음, 미측정)
