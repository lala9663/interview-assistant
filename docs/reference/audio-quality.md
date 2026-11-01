# 음성 품질

> 다루는 것: 전사 품질을 마이크부터 좌우하는 것(입력 형식, 에코, 잡음, 말 구간 자르기, 답변 끝 판단, 환각)과 품질을 재는 법.
>
> 상태: 구현됨(마이크 경로, 서버 잡음 억제 두 가지, [audio-input.md](../audio-input.md)), 일부 계획(WebRTC, 실제 면접 녹음으로 다시 재기) · 작성 2026-10-27 · 확인: 2026-11-01

전사 품질은 STT 모델보다 그 앞(마이크, 에코, 잡음, 말 구간 자르기)에서 많이 갈린다. 이 문서는 마이크 입력의 설정과 그 근거를 모은다. 실제로 구현한 경로와 기본값은 [audio-input.md](../audio-input.md)에 있고, 비대면 WebRTC 입력(11단계)은 아직이다. 모델 비교는 [stt.md](stt.md), 화자 나누기는 [diarization.md](diarization.md), 이 PC에서 잰 Whisper 값은 [whisper-benchmark.md](../whisper-benchmark.md).

## 1. 지금 상태

| 항목 | 상태 |
| --- | --- |
| 실시간 면접 음성 | 면접실 마이크(브라우저 getUserMedia → AudioWorklet 16kHz PCM16 → WebSocket, 막히면 HTTP)를 받는다(2026-10-28, [audio-input.md](../audio-input.md)). 마이크를 붙이기 전에는 가상 지원자 대본(텍스트)이 흐른다. WebRTC(비대면)는 아직 없다 |
| 마이크로 STT 시험 | 관리자 > 모델 설정 > STT 연결 테스트에서 5~10초 녹음은 된다. Chrome·Edge에서 http://localhost:5173 을 열어야 한다(Claude 앱 안 브라우저는 마이크를 막는다). 실시간 면접 화면에는 마이크 대신 쓰는 진단용 샘플 음성이 있다 |
| 말 구간 자르기 | 마이크 경로가 먼저 Silero VAD로 말소리만 남기고(앞 128ms·뒤 300ms 여유, 나머지는 디지털 무음) STT에 넣는다(`audio.vad`). 그 안에서 로컬 Whisper가 다시 침묵 500ms로 발화를 나눈다(`providers/stt/faster_whisper.py`) |
| 답변 끝 판단 | 관리자 화면에서 고른다(`audio.turn`): 침묵 기준(ms 조정) 또는 Smart Turn v3.2. 실사용 기본은 Smart Turn(판정 시작 1초, 기준 0.8, 최대 3초), 파일이 없으면 침묵 2초. 답이 닫힌 뒤 이어 말하면 같은 답에 붙는다. 다음 질문 기록·세션 종료도 답을 닫는다 |
| 잡음 억제·에코 제거 | 브라우저 AEC 켬, NS·AGC 끔(마이크 설정에서 바꿈). 서버 잡음 억제는 RNNoise·DeepFilterNet3를 고를 수 있고 기본 끔(`audio.denoise`, 소음 섞은 한국어 측정에서 CER을 낮추지 못했다) |
| 녹음 저장, 사후 전사 흐름 | 동의한 면접은 원본 영역에 WAV로 저장. STT 사후에서 "면접 뒤 녹음 재전사"를 켜면 면접 뒤 다시 전사해 따로 저장(질문별 나누기·채점 반영은 아직) |

## 2. 입력 형식

| 항목 | 값 | 이유 |
| --- | --- | --- |
| 표본 추출률 | 16kHz | Whisper는 입력을 16kHz로 바꿔 쓴다. Google은 16kHz 이상으로 녹음하고 다시 뽑지(리샘플) 말라고 권한다 |
| 채널 | 모노, 사람마다 한 채널 | 여러 마이크를 한 채널로 섞으면 화자를 다시 나눠야 한다. Google도 사람별 채널이 있으면 채널마다 따로 보내라고 권한다 |
| 표본 형식 | 16비트 PCM (`PCM16_16K`, `providers/base.py`) | 압축하지 않은 형식. 파일은 PyAV로 이 형식으로 풀어 넣는다(`providers/audio.py`) |
| 브라우저 | 보통 48kHz로 잡힌다 | `getUserMedia`의 `sampleRate` 제약은 "가능하면"일 뿐이고, Web Audio는 장치 표본 추출률을 따른다. 서버나 AudioWorklet에서 16kHz로 한 번만 뽑는다 |
| 압축 | 녹음·전송은 무손실이 좋다 | Google 권장 순서: FLAC·LINEAR16 → (손실이 필요하면) AMR_WB → OGG_OPUS. WebRTC 통화 트랙은 Opus(손실)라, 사후 전사용 원음을 따로 남길지 11단계에서 정한다 |
| 스트리밍 조각 | 100ms 안팎 | Google 스트리밍 권장 프레임 크기 |

## 3. 대면 면접: 마이크

- **지원자 자리에 마이크를 따로 두고 입 가까이 둔다.** Google은 마이크를 말하는 사람에게 최대한 가까이 두라고 하고, Microsoft는 삭제 오류(말이 빠짐)가 많으면 대개 신호가 약해서라며 소리 나는 곳 가까이에서 받으라고 한다. 방 가운데 마이크 하나는 울림과 면접관 목소리를 같이 잡는다.
- **면접관 목소리가 지원자 마이크에 섞이는 것(누화)을 줄인다.** 지향성 마이크를 지원자 쪽으로 향하게 한다. 섞이면 면접관 질문이 지원자 답변 전사에 끼어 꼬리질문과 채점이 흔들린다. 면접관 쪽 마이크도 있으면 두 마이크의 소리 크기를 비교해 거를 수 있다([diarization.md](diarization.md) 2장).
- **노트북 내장 마이크를 쓰지 않는다.** 면접관이 메모하는 타자 소리를 크게 잡는다.
- **소리가 찢어지지(클리핑) 않게** 입력 음량을 맞춘다(Google 권장).
- **방**: 유리벽·빈 회의실은 울림이 크다. 같은 방, 같은 마이크로 여러 번 재 본다.
- **스피커가 없으니 에코 제거는 필요 없다.**

## 4. 비대면 면접: 에코

- 상대방 목소리가 내 스피커에서 나와 내 마이크로 다시 들어가는 것이 에코다. 지원자 쪽에서 생기면 **면접관 목소리가 지원자 트랙에 섞인다.** 트랙 = 사람이라는 전제가 깨져 면접관 말이 지원자 답변으로 전사된다.
- 대책은 브라우저 에코 제거(AEC)를 켜고, 지원자에게 이어폰·헤드셋을 권하는 것이다. 이어폰이면 스피커 소리가 마이크로 거의 돌아가지 않는다.
- 참가자 트랙이 따로 오므로 화자분리는 필요 없다([model-selection.md](../model-selection.md) 4장). 대신 에코가 남았는지는 재야 한다(10장 "누화 비율").

## 5. 브라우저 AEC·NS·AGC

`getUserMedia`의 오디오 옵션 셋이다. Chrome의 처리는 WebRTC 오디오 처리 모듈(AEC3, AGC2, NS)이 한다.

| 옵션 | 하는 일 | 비대면 통화 | 대면 녹음 |
| --- | --- | --- | --- |
| `echoCancellation` (AEC) | 스피커로 나간 소리를 마이크 입력에서 뺀다 | 켠다 (필수) | 필요 없음 |
| `noiseSuppression` (NS) | 지속되는 배경 잡음을 줄인다 | 통화 품질 때문에 켠다. STT 영향은 잰다 | 끈다 (재 보고 바꾼다) |
| `autoGainControl` (AGC) | 작은 소리를 키우고 큰 소리를 줄인다 | 같음 | 끈다 (재 보고 바꾼다) |

- 무료이고 브라우저가 한다. Chrome·Firefox·Safari 모두 셋의 기본값이 켜짐이다(2021년 W3C 논의 기준. 지금 Chrome 공식 문서로는 확인 필요). 값을 그냥 주면 "요청", `exact`로 주면 "필수"다.
- **STT 앞에서는 NS·AGC를 끄라는 것이 일반 권고다.** Google STT 권장 사항은 잡음 처리를 모두 끄고 AGC를 쓰지 말라고 하고, W3C 명세도 소리를 바꾸지 않으려면 AGC·NS를 끄는 것이 바람직하다고 적는다.
- 비대면은 통화와 STT가 같은 트랙을 쓰면 통화 품질 때문에 켜 둘 수밖에 없다. 켠 것과 끈 것의 CER을 재서 정한다. 같은 마이크에서 설정이 다른 트랙을 두 개 받을 수 있는지는 확인 필요다.

## 6. 말 구간과 답변 끝 판단

두 층이 있다.

| | 발화 끝 | 답변 끝 (답변 닫힘) |
| --- | --- | --- |
| 무엇 | 한 문장·한 덩어리 말이 끝남 | 지원자가 이 질문에 대한 답을 다 함 |
| 누가 | VAD (침묵 500ms) | 지금은 STT 스트림 종료·다음 질문 기록·세션 종료 |
| 결과 | 그 발화의 확정 전사(`segment.final`) | `qa.answered` → 꼬리질문 요청 |
| 틀리면 | 문장이 쪼개져 전사가 조금 나빠진다 | 꼬리질문이 너무 이르거나 늦다 |

### VAD (Silero)

- MIT 라이선스. faster-whisper 1.2.1에 v6 ONNX 모델이 들어 있어 따로 설치하지 않는다. 8kHz·16kHz를 받고, 16kHz에서 512표본(32ms) 조각마다 판단한다. README는 조각 하나를 CPU 스레드 하나로 1ms 안에 처리한다고 적는다.
- 말이 있는지만 본다. 말이 끝났는지(생각하느라 멈춘 것인지)는 모른다.

### 침묵 길이만으로 정할 때

- 간단하다. 침묵이 N초 이어지면 답변 끝으로 본다. [model-selection.md](../model-selection.md) 2장은 약 2초로 예상했다.
- **짧으면** 지원자가 생각하느라 멈춘 것("음… 그때는…")을 끝으로 착각한다. 답변이 둘로 쪼개지고, 반쪽 답변으로 꼬리질문이 뜬다. 면접 답변은 일상 대화보다 생각하는 멈춤이 길다.
- **길면** 첫 꼬리질문이 그만큼 늦게 뜬다. 면접관은 이미 다음 말을 시작했을 수 있다.
- 클라우드 STT에도 비슷한 손잡이가 있다. Google STT v2는 말 시작·끝 이벤트(`enable_voice_activity_events`), 침묵 제한(`voice_activity_timeout`, 0.5~60초), 끝 판정 민감도(`endpointing_sensitivity`: STANDARD·SHORT·SUPERSHORT, 짧을수록 빠르지만 발화가 쪼개진다)를 준다. CLOVA는 끝 신호를 보내지 않으면 최대 10초 모은다([model-selection.md](../model-selection.md) 3장).

### 소리로 말끝을 판단할 때 (Pipecat Smart Turn)

| 항목 | 내용 |
| --- | --- |
| 버전·라이선스 | v3.2, BSD-2-Clause |
| 크기 | 파라미터 약 8M. CPU용 int8 ONNX 8MB, GPU용 fp32 32MB |
| 입력 | 16kHz 모노 PCM, 마지막 최대 8초. 텍스트가 아니라 소리(억양, 말끝)를 본다 |
| 출력 | 끝남(1) / 아직(0), 기준 0.5 |
| 언어 | 23개, 한국어 포함 |
| 한국어 정확도 (공개 평가) | v3.2 CPU 96.96% (889건). 끝나지 않은 말을 끝으로 본 비율(조기 끊김) 2.25%, 그 반대 0.79%. 두 비율은 전체 건수로 나눈 값이다. 평가 세트에 TTS 합성 음성이 섞여 있어 실제 면접과 다를 수 있다 |
| 속도 | 클라우드 CPU 9~37ms + 전처리 7~9ms (Daily 발표) |
| 조합 | Pipecat 권장: VAD가 0.2초 침묵을 보면 그때까지의 턴을 Smart Turn에 넣는다. "아직"이면 계속 듣고, 침묵이 3초를 넘으면 끝으로 본다 |

- 이 프로젝트에 맞추면: VAD 짧은 침묵 → Smart Turn → "끝"이면 답변 닫힘, 아니면 최대 침묵(예: 3초)까지 기다린다. 면접관이 다음 질문을 기록하면 바로 닫는다.
- 한국어 면접 녹음에서 조기 끊김이 얼마나 나는지 재 봐야 한다(10장).
- **LiveKit turn detector는 쓰지 않는다.** STT 텍스트를 보는 모델(Qwen2.5-0.5B 미세조정, 한국어 지원)이지만, 라이선스가 LiveKit Agents 밖에서 쓰는 것을 막는다([libraries.md](libraries.md) 5장).

### 꼬리질문 타이밍을 덜 민감하게

- 1~2초 침묵에서 꼬리질문 생성을 미리 시작하고, 답변이 이어지면 버린다([model-selection.md](../model-selection.md) 2장).
- 답변 도중 확정 전사가 쌓이면 질문 은행 후보를 미리 찾는다([implementation-order.md](../implementation-order.md) 남은 항목).
- 면접관이 다음 질문을 기록하면 확실한 끝이다. 이 신호는 이미 쓴다.

## 7. 서버 쪽 잡음 억제

| 이름 | 라이선스 | 입력 | 상태 |
| --- | --- | --- | --- |
| RNNoise | BSD-3-Clause | 48kHz, 10ms 프레임 | 구현됨, 기본 끔 (`rnnoise`, 지연 35ms) |
| DeepFilterNet3 | MIT 또는 Apache-2.0 | 48kHz, 10ms 프레임, 앞보기 20ms | 구현됨, 기본 끔 (`deepfilternet`, 지연 45ms) |

- **기본은 끈다.** 잡음 억제는 사람이 듣기 좋게 만들지만, 그 과정의 변형(아티팩트)이 STT 정확도를 떨어뜨린다는 연구가 여럿이다. 한 채널 잡음 억제의 아티팩트가 STT 저하의 주원인이라는 분석(Iwamoto 외, 2022), Whisper를 포함한 4개 STT 모두에서 잡음 억제가 오류를 늘렸다는 의료 음성 연구(2025), 음원 분리를 앞에 붙이면 Whisper의 WER·CER이 오른 연구(2026)가 있다. 잘 설계한 앞단은 도움이 된다는 연구도 있어 일괄 결론은 아니다.
- 둘 다 48kHz를 받는다. 이 프로젝트는 서버가 받은 16kHz를 48kHz로 올려 걸고 다시 내린다(왕복 5ms). 모델은 8kHz 위가 빈 소리를 본다. 브라우저 48kHz 단계에서 걸려면 모델을 브라우저에 넣어야 한다.
- **잰 결과**(2026-11-01, 낭독에 사무실·에어컨·선풍기·키보드 소음을 20·10·5dB로 섞음, [audio-input.md](../audio-input.md) 7장): 말소리가 잘 들리는 표본에서는 두 억제기 모두 Whisper small·large-v3의 CER을 올렸다. 연구들과 같은 방향이다. DeepFilterNet3는 모든 SNR에서 끔보다 나빴다. RNNoise는 키보드 소음 때문에 VAD가 작은 목소리를 놓칠 때만 나아졌다(CER 18 → 9%). 에어컨 소음에서는 크게 나빠졌다. 그래서 기본은 끔이다.
- 실제 면접 녹음이 생기면 끈 것·RNNoise·DeepFilterNet3를 같은 방식으로 다시 잰다.

## 8. Whisper가 침묵에서 지어내는 문제

- Whisper는 침묵·잡음 구간에서 하지 않은 말을 지어낼 수 있다(환각). "Careless Whisper"(FAccT 2024)는 전사의 약 1%에 오디오에 없는 문장이 통째로 들어갔고 그중 38%가 해로운 내용이었으며, 말 사이 침묵이 긴 화자에서 더 잦았다고 보고했다. 면접 답변도 생각하는 침묵이 길다.
- 면접에서는 지어낸 문장이 지원자 답변으로 저장되고, AI 채점이 그 문장을 근거로 인용할 수 있다.

| 대책 | faster-whisper 기본값 | 이 프로젝트 |
| --- | --- | --- |
| VAD로 말 구간만 넣기 (`vad_filter`) | 끔 | 사후 전사는 켬, 실시간은 VAD로 자른 발화만 디코딩 |
| 앞 구간 전사를 다음 구간 프롬프트로 잇기 (`condition_on_previous_text`) | 켬 | 끔. 틀린 전사가 이어지며 반복되는 것을 막는다 |
| 말 없음 판정 (`no_speech_threshold` 0.6 + `log_prob_threshold` -1.0) | 켬 | 기본값 그대로 |
| 반복 판정 (`compression_ratio_threshold` 2.4) | 켬 | 기본값 그대로 |
| 긴 침묵 건너뛰기 (`hallucination_silence_threshold`) | 끔. 단어 시각이 켜져 있어야 동작 | 쓰지 않음 |
| 용어 힌트를 짧게 | | 관리자 화면 안내: 길면 오히려 엉뚱한 말을 지어낼 수 있다 |

- 남은 일: 침묵·잡음만 있는 녹음을 넣어 글자가 나오는지 재기(10장 "환각률").

## 9. 품질이 어디로 이어지나

```
마이크·에코·잡음 ─▶ VAD·답변 끝 ─▶ STT 오류 ─┬─▶ 비식별화: 이름을 다른 글자로 받아 적으면 탐지를 비껴간다
                                          ├─▶ 꼬리질문: 틀린 용어로 검색·생성, 반쪽 답변으로 질문
                                          ├─▶ 평점: 틀린 전사나 섞인 면접관 말이 근거로 인용된다
                                          └─▶ 화자: 에코·누화로 면접관 말이 지원자 답변이 된다
```

| 이어지는 곳 | 영향 | 지금 대책 | 남은 것 |
| --- | --- | --- | --- |
| 비식별화 | STT가 이름을 비슷한 다른 글자로 적으면 지원서 값과 정확히 맞지 않아 토큰으로 안 바뀐다. 반쯤 들린 이름("홍길")도 못 잡는다 | 부분 전사는 마지막 어절과 숫자·`@`가 붙은 어절을 빼고 보낸다. 확정 전사는 통째로 비식별화한다. LLM 호출 직전 가드가 한 번 더 본다 | OCR 구간에만 쓰는 너그러운 탐지기(자모 거리)를 전사에도 쓸지, 실제 녹음으로 재 보고 정한다 |
| 꼬리질문 | 전문 용어·약어를 틀리면 질문 은행 검색의 단어 일치 점수가 소용없고, AI가 엉뚱한 것을 묻는다. 답변 끝을 일찍 판단하면 반쪽 답변으로 묻는다 | 기술 용어 힌트, 질문 은행의 의미 검색 | 실제 면접 녹음으로 용어 오류율 재기 |
| 평점 | AI 채점은 답변을 인용해 근거를 댄다. 전사가 틀리면 근거가 틀린다 | 공식 기록과 채점 근거는 사후 전사(더 정확한 모델, 앞뒤 문맥)로 하기로 했다([model-selection.md](../model-selection.md) 1장) | 사후 전사 흐름(10단계) |
| 화자 | 섞인 면접관 말이 지원자의 답으로 채점된다 | 비대면은 참가자 트랙, 대면은 지원자 마이크 따로 | 누화 비율 재기 |

## 10. 재는 법

| 무엇 | 어떻게 | 도구 |
| --- | --- | --- |
| 정확도 (CER) | 동의 받은 실제 면접 녹음에 정답 전사를 달고 잰다. CER = (바꾼 글자 + 빠진 글자 + 넣은 글자) ÷ 정답 글자 수, 이 저장소는 공백·문장부호를 빼고 센다. 한국어는 띄어쓰기가 일정하지 않아 WER이 흔들리므로 한국어 STT 연구도 CER(음절 단위)을 쓴다 | `scripts/bench_whisper.py --manifest` |
| 용어 오류 | 직군 용어 목록이 정답 전사대로 나왔는지 따로 센다. 전체 CER이 낮아도 용어가 틀리면 꼬리질문이 망가진다 | 위 결과에 목록 대조 (스크립트 없음) |
| 지연 | 발화 끝 → 확정 전사, 답변 끝 → 첫 꼬리질문 후보. 속도는 이 저장소의 "실시간 대비"(음성 길이 ÷ 처리 시간, 흔히 RTFx)로 적는다. RTF는 그 역수다 | `bench_whisper.py`(스트리밍), 관리자 > 꼬리질문 지표 |
| 답변 끝 오판정 | 녹음에 사람이 "답변 끝" 시각을 표시하고, 판단기가 그 전에 닫은 비율(조기 닫힘)과 끝난 뒤 닫기까지 걸린 시간을 잰다. 침묵 1·1.5·2·3초와 Smart Turn을 같은 녹음으로 비교 | 없음 (만들 것) |
| 환각률 | 침묵·잡음·숨소리만 있는 구간을 넣고 글자가 나온 비율 | 없음 (만들 것) |
| 누화 비율 | 지원자 트랙 전사에 면접관 말이 섞인 글자 비율 | 없음 (만들 것) |
| 잡음 억제 효과 | 같은 녹음을 끈 것·RNNoise·DeepFilterNet으로 각각 전사해 CER 비교. VAD가 놓친 말소리·잡음을 말로 본 시간, 답변 끝 판정도. 브라우저 NS·AGC 켬·끔도 같은 방식 | `scripts/bench_denoise.py` (지금은 낭독에 소음을 섞은 것, [audio-input.md](../audio-input.md) 7장) |

조건을 같이 적는다: 마이크 종류와 거리, 방, 이어폰 여부, 브라우저 옵션 값, PC(전원 연결 여부. 이 노트북은 충전 중에 2배 느려졌다, [whisper-benchmark.md](../whisper-benchmark.md)).

## 11. 아직 하지 않은 것

2026-10-28 마이크 입력([audio-input.md](../audio-input.md))으로 한 것: 브라우저 마이크 입력과 녹음 저장, VAD로 말소리만 STT에 넣기, 답변 끝 침묵 길이와 Smart Turn 비교(생각하는 멈춤이 든 한국어 32건, 낭독·TTS)와 기본값 결정, 이 노트북의 말 끝 → 확정 전사 → 답변 닫힘 → 첫 꼬리질문 카드 측정, 면접 뒤 녹음 재전사(저장까지). 2026-11-01: 서버 잡음 억제 RNNoise·DeepFilterNet3 구현과 소음 섞은 한국어 측정(기본 끔 유지).

남은 것:

- WebRTC 입력(비대면 참가자 트랙), 한 세션에 마이크 두 개, 대면 화자분리.
- 재전사 결과를 질문별로 나누고 채점에 쓰기.
- 실제 면접 녹음(동의 받은 것)으로 답변 끝 판정 다시 재기(실제 멈춤 분포, Smart Turn의 한국어 실제 음성 정확도). 이번 비교는 낭독과 TTS에 멈춤을 넣은 것이다.
- 브라우저 NS·AGC 켬·끔의 CER 비교. 서버 잡음 억제는 소음 섞은 낭독으로 재 두었다([audio-input.md](../audio-input.md) 7장). 실제 면접 녹음으로 다시 잰다.
- 실제 면접 녹음으로 CER·용어 오류·환각률·누화 비율 재기.
- 전사에 너그러운 비식별 탐지기를 쓸지 결정.

## 출처

확인 날짜 2026-10-27.

- [Google Cloud Speech-to-Text 권장 사항 (2026-10-22 갱신)](https://docs.cloud.google.com/speech-to-text/docs/best-practices)
- [Google STT v2 음성 활동 이벤트](https://docs.cloud.google.com/speech-to-text/v2/docs/voice-activity-events), [StreamingRecognitionFeatures (endpointing_sensitivity)](https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v2.types.StreamingRecognitionFeatures)
- [Microsoft: Custom Speech 정확도 평가 (WER, 삭제 오류)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-custom-speech-evaluate-data), [Microsoft: 마이크 권장 사양](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-sdk-microphone)
- [Whisper 오디오 처리 (16kHz)](https://github.com/openai/whisper/blob/main/whisper/audio.py)
- [MDN echoCancellation](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation), [noiseSuppression](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/noiseSuppression), [autoGainControl](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/autoGainControl), [sampleRate](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/sampleRate)
- [W3C Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/), [기본값 논의 (W3C, 2021)](https://lists.w3.org/Archives/Public/public-webrtc-logs/2021Mar/0012.html)
- [WebRTC 오디오 처리 모듈](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/g3doc/audio_processing_module.md)
- [Silero VAD](https://github.com/snakers4/silero-vad), [라이선스](https://raw.githubusercontent.com/snakers4/silero-vad/master/LICENSE)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [vad.py (VadOptions 기본값)](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/vad.py), [transcribe.py (환각 대책 기본값)](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py)
- [Pipecat Smart Turn](https://github.com/pipecat-ai/smart-turn), [smart-turn-v3 모델](https://huggingface.co/pipecat-ai/smart-turn-v3), [v3.2 CPU 언어별 평가](https://huggingface.co/pipecat-ai/smart-turn-v3/blob/main/benchmarks/smart-turn-v3.2-cpu.md), [v3.1 속도 (Daily)](https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/), [Pipecat 턴 판정 설정](https://docs.pipecat.ai/server/utilities/turn-detection/smart-turn-overview)
- [LiveKit turn detector](https://huggingface.co/livekit/turn-detector), [라이선스](https://huggingface.co/livekit/turn-detector/blob/main/LICENSE)
- [RNNoise](https://github.com/xiph/rnnoise), [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)
- Iwamoto 외, [How Bad Are Artifacts?: Analyzing the Impact of Speech Enhancement Errors on ASR (Interspeech 2022)](https://arxiv.org/abs/2201.06685)
- Chondhekar 외, [When De-noising Hurts (arXiv 2512.17562, 2025)](https://arxiv.org/abs/2512.17562)
- Islam 외, [When Audio Separation Hurts Zero-Shot ASR (arXiv 2603.04710, 2026)](https://arxiv.org/abs/2603.04710)
- Koenecke 외, [Careless Whisper: Speech-to-Text Hallucination Harms (FAccT 2024)](https://arxiv.org/abs/2402.08021)
- [CER 정의 (Hugging Face evaluate)](https://huggingface.co/spaces/evaluate-metric/cer/blob/main/README.md), [K-Wav2vec 2.0 (한국어 띄어쓰기와 CER)](https://arxiv.org/abs/2110.05172), [RTFx (Open ASR Leaderboard)](https://arxiv.org/abs/2510.06961)

### 확인 필요

- 지금 Chrome의 AEC·NS·AGC 기본값을 밝힌 Chrome 공식 문서(근거는 2021년 W3C 논의), Chrome이 `getUserMedia`에 AEC3를 쓴다는 공식 문서(근거는 WebRTC 소스)
- Chrome이 `sampleRate` 제약을 실제로 지키는지, 같은 마이크에서 처리 설정이 다른 트랙 두 개를 받을 수 있는지
- Smart Turn 한국어 평가 세트의 합성·실제 음성 비율과 실제 면접 음성에서의 정확도, v3.2에서 바뀐 점 (v3.2가 최신이고 BSD-2-Clause임은 2026-10-28 Hugging Face에서 확인)
- LiveKit turn detector의 지연 시간
- ~~Silero VAD v6 ONNX 파일 크기~~ 1,245,151바이트(faster-whisper 1.2.1, 2026-10-28 확인)
- ~~RNNoise·DeepFilterNet 최신 버전~~ RNNoise는 xiph/rnnoise `70f1d25`(2025-02, v0.2 뒤, pyrnnoise 0.4.5 휠), DeepFilterNet은 v0.5.6(2023-08)이 마지막 릴리스(2026-10-30 확인)
- Microsoft가 STT 앞단에서 NS·AGC를 끄라고 명시한 문서
