# AI 모델 선택 메모

2026-10-26 · 관리자 > 모델 설정과 로컬 Whisper를 붙인 뒤 정리한 판단 근거. 측정은 [Whisper 측정](whisper-benchmark.md), 교체 구조는 [API 계약](api-contract.md) "관리자 > 모델 설정".

모델은 아직 정하지 않았다. 사내에 어떤 모델(LLM·STT)이 허용되는지 모르고, GCP는 이 PoC를 위해 직접 만들 환경이다. 그래서 무엇이 정해져도 관리자 화면에서 바꿔 끼우는 구조로 두었고, 이 문서는 고를 때의 기준과 지금까지 확인한 사실을 모은다.

## 1. 역할마다 무엇이 중요한가

| 역할 | 언제 | 우선순위 | 비고 |
| --- | --- | --- | --- |
| STT 실시간 | 면접 중, 지원자가 말하는 동안 | 속도 | 면접관 화면에 전사를 바로 띄우고, 답변이 끝나면 꼬리질문을 요청한다. 몇 초 단위로 끊어 받아 적어 오류가 더 난다 |
| STT 사후 | 면접이 끝난 뒤, 녹음 파일 전체로 | 정확도 | 공식 기록과 AI 채점 근거. 앞뒤 문맥이 있어 더 정확하다(같은 Whisper medium이 실시간 5.4%, 사후 1.2% 오류). 대면 면접의 화자분리, 질문-답변 나누기(10단계), 실시간 STT가 끊긴 면접의 기록 복구도 여기서 한다. 느려도 되니 가장 정확한 모델을 쓴다 |
| LLM 꼬리질문 | 면접 중, 답변마다 | 속도 (첫 글자 2초 이하, 7단계) | 지금은 LLM 주 모델을 쓴다 |
| LLM 채점·역량 사전 | 면접 뒤 백그라운드, 답변마다 3회 | 품질 | 면접관 점수와의 일치도가 게이트 기준(12단계) |
| LLM 서류 선별 | 업로드할 때 | 비용 (대량) | |

지금 상태: STT 사후는 화면에서 고르고 테스트하는 것까지다. 녹음 파일 저장(11단계)과 사후 전사 흐름(10단계)이 아직 없다. STT 실시간은 마이크 입력을 붙이기 전까지 가상 지원자 대본(fake)이다.

## 2. 답변이 끝나고 꼬리질문이 뜨기까지 (예상)

```
지원자 말 멈춤 ─①─ "답변이 끝났다" 판단 ─②─ 마지막 문장 전사 확정 ─③─ LLM 첫 꼬리질문 글자 ─④─ 후보 2~3개 완성
```

| 구간 | 이 PC (Whisper medium, CPU) | 스트리밍 STT (Chirp·CLOVA) 또는 GPU Whisper |
| --- | --- | --- |
| ① 답변 끝 판단 | 약 2초 (문장 사이 쉼과 구분하려면 몇 초 기다려야 함) | 약 2초 |
| ② 마지막 문장 확정 | 7.7~8.9초 (측정) | 1초 이하 (추정) |
| ③ LLM 첫 글자 | 1~2초 (추정, 목표 2초 이하) | 1~2초 (추정) |
| 첫 꼬리질문이 보일 때까지 | 약 9~11초 (①은 ②와 겹침) | 약 3~4초 |
| ④ 후보 2~3개 완성 | +3~5초 | +3~5초 |

- Whisper 숫자만 잰 값이다. LLM과 스트리밍 STT는 연결 전이라 추정이다. small을 쓰면 ②가 3.5~5.7초(전체 5~8초)지만 전사 오류가 많아(13%) 꼬리질문 품질도 떨어진다.
- 앞 문장들은 지원자가 말하는 동안 확정되므로 기다리는 것은 마지막 문장 하나다. 답변이 길어도 간격은 같다.
- ①의 침묵 길이는 마이크 입력을 붙일 때 정한다. 짧으면 말하는 도중에 답변이 닫히고, 길면 간격이 는다. 지금 데모는 대본이 끝나면 바로 닫힌다.
- 면접관이 사전 질문이나 직접 쓴 질문을 하면 AI를 기다리지 않는다. 꼬리질문 후보는 옆에 따로 뜬다.
- 더 줄이려면: 1~2초 침묵에서 꼬리질문 생성을 미리 시작하는 방식(답변이 이어지면 버림). 실제 모델로 재고 길면 검토한다.

## 3. 실시간 STT 선택지

| 선택지 | 응답 방식 | 속도 | 데이터 위치 | 확인한 것 |
| --- | --- | --- | --- | --- |
| Whisper, 이 PC CPU | 발화가 끝나면 그 구간을 통째로 전사 | 말 끝 → 확정 small 3.5~5.7초, medium 7.7~8.9초 (측정) | 이 PC | 호출마다 30초 창을 통째로 인코딩해 짧은 발화도 비용이 같다. 11단계 기준(부분 전사 0.5초 이하)은 CPU로 못 맞춘다 |
| Whisper, GPU 서버 | 같음 | 훨씬 빠름 (미측정) | 회사 서버 | 같은 provider에 device 옵션을 열면 된다. 음성이 회사 밖으로 안 나가 보안상 가장 좋다 |
| Google Speech-to-Text v2 (Chirp 3) | 스트리밍 API: 말하는 도중 중간 결과, 끝나면 확정 | 공식 수치 없음, 미측정 | Google Cloud | `StreamingRecognize` 지원, 한국어 GA. 중간 결과에 `is_final`과 stability. 발화 끝 판단 민감도 조정 가능. 자동 문장부호·화자분리는 Preview, 단어 시각 미지원. 리전은 us·eu GA, 아시아는 문서마다 표기가 달라 확인 필요 |
| NAVER CLOVA Speech | 스트리밍 API (gRPC) | 공식 수치 없음, 미측정. 네이버 뉴스·쇼핑라이브 실시간 자막에 쓰인다고 발표 | 네이버 클라우드 (한국 리전), 회사 밖 | 한국어·영어·일본어. 입력이 16kHz 모노 16비트 PCM이라 우리 형식과 같다. 발화 끝 신호(`epFlag`)를 보내지 않으면 최대 10초(`unvoiceTime`) 모았다가 확정을 준다. 스트리밍 화자분리가 안 나오는 사례, 채널 15개 한도 |
| Azure, AWS Transcribe, Deepgram 등 | 스트리밍 API | 미측정 | 회사 밖 | 한국어 지원. 음성 원본이 외부로 나간다 |

회사 밖 서비스는 "음성 원본은 외부로 보내지 않음" 원칙에 걸린다. 관리자 화면에서 "외부" 배지와 경고·사유 단계를 거치고, 그 전에 보안 승인이 필요하다.

## 4. 조합

### 회사에 확인할 것

1. 승인된 LLM이 있는가 (사내 자체 LLM: 설정 파일에 `samsung_gauss` 후보, 회사가 계약한 클라우드 LLM)
2. 사내 STT가 있는가, 면접 음성을 회사 밖으로 보내도 되는가
3. 쓸 수 있는 클라우드가 있는가 (GCP·Azure·AWS 계약), 데이터를 어느 리전에 둬야 하는가
4. GPU 서버를 받을 수 있는가

### 답에 따른 조합

| 상황 | STT 실시간 | STT 사후 | LLM |
| --- | --- | --- | --- |
| GPU 서버가 있다 | 로컬 Whisper (GPU) | 로컬 Whisper large-v3 | 승인된 LLM |
| 승인된 클라우드만 있다 | 그 클라우드의 스트리밍 STT | 그 클라우드의 배치 STT 또는 로컬 Whisper large-v3 | 그 클라우드의 LLM |
| 둘 다 없다 | 로컬 Whisper CPU (확정까지 8초 이상 감수, 또는 small) | 로컬 Whisper large-v3 | 사내 LLM |

### PoC (직접 만들 GCP 프로젝트)

"이 서비스가 면접에서 쓸 만한가"를 빨리 보이기 위한 임시 선택이다.

- STT 실시간: Chirp 3 스트리밍
- STT 사후: 로컬 Whisper large-v3 (지금 바로 된다, 샘플 오류 0%). Chirp 배치와 비교해 정한다
- LLM: Vertex AI의 Claude. 채점·역량 사전 Opus 5.5, 서류 선별 Haiku 5.5, 꼬리질문은 주 모델로 재 보고 결정
- 화자분리: 별도 검토 (Whisper에는 없고 Chirp 3은 Preview)

판단 기준: 실시간 부분 전사 0.5초 이하, 꼬리질문 첫 글자 2초 이하, 실제 면접 녹음의 오류율. GCP가 생기면 관리자 화면의 연결 테스트와 `scripts/bench_whisper.py`처럼 같은 조건에서 잰다.

## 5. 정한 것과 미룬 것

| 항목 | 결정 | 언제 다시 |
| --- | --- | --- |
| 꼬리질문 전용 LLM 역할 | 지금은 만들지 않는다. 주 모델로 2초를 맞추는지 모르고, 사내 허용 LLM이 하나뿐일 수 있다. 필요하면 관리자 화면에 역할 하나를 더하는 작은 작업이다 | 3단계에서 꼬리질문 첫 글자 시간과 비용을 잰 뒤 |
| 데이터 위치 배지 "사내 GCP" | 미정. Google·Vertex 계열을 지금 "사내 GCP"로 표시하고 외부 경고를 띄우지 않는다. GCP가 회사 승인 없이 직접 만드는 프로젝트라면 이름을 바꾸거나 "외부"로 취급할지 정해야 한다 | GCP 프로젝트를 만들 때 |
| 답변 끝 판단 침묵 길이 | 미정 (2초 안팎 예상) | 실시간 면접 마이크 입력을 붙일 때 |
| 실시간 STT | 미정. 이 PC CPU의 Whisper로는 11단계 기준을 못 맞춘다 | 회사 확인 4항목의 답이 오면 |

## 출처

- [Chirp 3 Transcription (Google Cloud)](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)
- [Chirp 3 model (Speech-to-Text v2)](https://cloud.google.com/speech-to-text/v2/docs/chirp_3-model?hl=en)
- [StreamingRecognitionFeatures (Speech v2)](https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v2.types.StreamingRecognitionFeatures)
- [CLOVA Speech 개요 (NAVER Cloud)](https://guide.ncloud-docs.com/docs/en/clovaspeech-overview)
- [CLOVA Speech gRPC API](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-grpc.md)
- [CLOVA Speech 문제 해결](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-troubleshoot.md)
- [Naver Cloud launches real-time streaming feature (KED Global, 2024-02)](https://www.kedglobal.com/newsView/ked202402020009)
