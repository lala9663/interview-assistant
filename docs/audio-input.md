# 실시간 면접 마이크 입력

> 다루는 것: 실시간 면접 화면이 면접실 마이크(또는 진단용 샘플 음성)를 받아 말소리만 전사하고, 지원자가 답변을 마쳤는지 판단해 꼬리질문을 요청하는 경로. 오류 코드, 면접 뒤 재전사, 이 노트북 측정, 사내 환경별 설정.
>
> 상태: 구현됨(대면 마이크, 서버 잡음 억제 RNNoise·DeepFilterNet3는 고를 수 있고 기본 끔). 비대면 WebRTC·마이크 두 개는 계획 · 확인: 2026-11-01

음성 품질의 근거는 [reference/audio-quality.md](reference/audio-quality.md), Whisper 속도는 [whisper-benchmark.md](whisper-benchmark.md), API는 [api-contract.md](api-contract.md) 3.3.

## 1. 흐름

```
브라우저                                     서버 (음성은 메모리와 원본 영역에만)
getUserMedia ──▶ AudioWorklet ──▶ WebSocket ──▶ MicrophoneSource ─┬─▶ WAV 녹음 (동의한 면접만, IA_RECORDINGS_DIR)
(또는 샘플 WAV)   16kHz PCM16     (막히면 HTTP     잡음 억제(기본 끔)  │
                  100ms 조각       청크로 대체)    → Silero VAD ────┼─▶ 말소리만 → 스트리밍 STT → 비식별화 → SSE 전사
                                                                  └─▶ 답변 끝 판정 → 답변 닫힘(qa.answered) → 꼬리질문
```

- 화면: 실시간 면접의 전사 칸 위 막대. 마이크 켜기/끄기, 입력 음량, 서버가 말소리를 듣는지(말소리/조용함), 질문 중 / 답변 듣는 중(Alt+1 / Alt+2), 전송 방식(WebSocket / HTTP 대체), 설정(입력, 에코 제거·잡음 억제·자동 음량), 문제는 짧은 코드로(6장).
- 녹음 동의가 없으면 마이크 버튼이 꺼져 있고 `NO-CONSENT`를 보여 준다. 답변은 수기로 적는다. 서버도 거절한다.
- 인증은 다른 API와 같다(쿠키, 지금 로그인한 면접관 `current_interviewer`). 에이전트 토큰으로는 열 수 없다(쓰기로 취급해 403).
- 관리자 > 모델 설정의 "음성 입력" 묶음: 음성 구간(VAD), 답변 끝 판정, 서버 잡음 억제([ai-models.md](ai-models.md)). 다른 역할처럼 테스트·적용·이력·되돌리기가 되고, 진행 중인 면접은 시작할 때의 설정을 쓴다.

## 2. 브라우저 입력

| 설정 | 기본값 | 이유 |
| --- | --- | --- |
| `echoCancellation` (AEC) | 켬 | 스피커로 나간 소리만 뺀다. 대면에서는 할 일이 거의 없고, 화면에서 소리가 나면 필요하다 |
| `noiseSuppression` (NS) | 끔 | 잡음 억제의 변형이 STT 오류를 늘린다는 연구가 많다. 켜려면 CER을 재 보고 정한다 |
| `autoGainControl` (AGC) | 끔 | STT 앞에서는 소리 크기를 바꾸지 않는 것이 권고다 |
| `channelCount` | 1 | 사람마다 한 채널 |

- 설정은 브라우저(localStorage)에 남고, 다음에 마이크를 켤 때 적용된다. 실제로 적용된 값(브라우저가 요청을 무시할 수 있다)과 장치 표본 추출률은 감사 로그 `audio.constraints`에 남는다.
- 변환은 AudioWorklet(`frontend/public/audio/pcm16-worklet.js`)이 한다. 장치 표본 추출률(보통 48kHz)의 입력을 출력 표본 하나에 들어가는 입력 표본들의 평균(박스 필터)으로 16kHz로 내리고, 채널이 여럿이면 섞고, 16비트로 바꿔 100ms(1,600표본, 3,200바이트)마다 페이지로 보낸다. 페이지는 받은 대로 서버로 보낸다. 같은 파일을 테스트가 그대로 돌린다.
- 전송은 WebSocket 먼저(`/api/sessions/{id}/audio`, 4초 안에 `ready`가 와야 함). 열리지 않으면 HTTP 청크(`POST …/audio/chunks`, 요청 하나씩 차례로, 밀리면 4초까지 묶음)로 바꾸고 `WS-BLOCKED`를 띄운다. 쓰다가 끊기면 HTTP로 이어 보내고 `WS-LOST`. 개발 서버는 Vite 프록시가 WebSocket도 넘긴다(`ws: true`).
- 마이크는 HTTPS(또는 localhost)에서만 열린다. 아니면 `MIC-HTTPS`.

## 3. 진단용 샘플 음성 (가짜 마이크)

마이크 대신 저장된 한국어 녹음을 같은 경로(AudioWorklet → 전송 → VAD → STT → 답변 끝 → 꼬리질문)로 흘려보낸다. 마이크 설정의 "입력"에서 고른다.

| 이름 | 길이 | 내용 |
| --- | --- | --- |
| `answer-pauses` (기본) | 16.6초 | FLEURS 한국어 낭독 두 문장. 첫 문장 안에 1.5초, 두 문장 사이에 1.9초 생각하는 멈춤 |
| `ko-fleurs-1894` | 11.5초 | FLEURS 한국어 낭독 한 문장 (STT 연결 테스트와 같은 샘플) |

- 쓰임: Claude 앱 안 미리보기 브라우저처럼 마이크가 막힌 곳에서 확인, 사람 목소리 없는 확인, 사내에서 마이크가 막혔을 때 나머지 경로 진단(샘플은 되는데 마이크가 안 되면 문제는 마이크 권한·장치 쪽).
- AudioWorklet도 HTTPS(또는 localhost)에서만 돌아 샘플도 `MIC-HTTPS`를 받는다. 샘플이 끝나면 무음을 계속 보내 서버가 답변 끝을 판정할 수 있게 한다. 샘플은 녹음 파일에 남기지 않는다. 전사는 그 면접의 답변으로 기록되니 시험용 면접에서만 쓴다.
- 서버는 묶인 샘플만 내준다(`GET /api/live/audio-samples/{name}`). 녹음은 내주지 않는다. 출처는 `src/interview_assistant/providers/samples/NOTICE.md`(CC BY 4.0).
- 자동 테스트: 백엔드는 같은 PCM을 WebSocket·HTTP로 보내고(`tests/test_audio_input.py`), 프론트는 getUserMedia·AudioContext·WebSocket을 모의로 바꿔 돌린다(`frontend/src/features/interview/audio/*.test.ts`).

## 4. 서버

`live/microphone.py`의 `MicrophoneSource`가 세션의 마이크다. 브라우저가 붙으면 그 세션은 데모 대본 대신 마이크를 듣는다(끊겨도 마이크를 기다린다).

1. **녹음**: 동의가 있으면 받은 조각을 그대로 원본 영역의 세션 WAV(`<IA_RECORDINGS_DIR>/<세션 id>.wav`, `recording_uri`)에 덧붙인다. 다시 연결하면 같은 파일에 이어 쓴다(마이크가 꺼져 있던 시간은 없다). 쓸 때마다 헤더 길이를 고쳐 써서 서버가 죽어도 그때까지는 재생된다. API로 내주지 않는다. 디스크 오류는 `REC-FAILED`로 알리고 전사는 계속한다.
2. **잡음 억제**: `audio.denoise`, 기본 끔. RNNoise·DeepFilterNet3를 고를 수 있다(7장). 마이크마다 따로 상태를 두고, 켜면 VAD·STT가 35~45ms 늦은 소리를 받는다.
3. **VAD**: Silero VAD v6가 32ms(512표본)마다 말소리 확률을 낸다. 0.5 이상이면 말소리, 말하는 중에는 0.35 아래로 떨어져야 끝(faster-whisper와 같은 이력 현상). 모델은 faster-whisper 패키지 안의 파일을 쓰고(1,245,151바이트, sha256 `4cbf549b…f1be17d2`, faster-whisper 1.2.1), 불러올 때 크기와 sha256을 확인한다. 다르면 `VAD-MISSING`. 조각을 나눠 넣어도 한 번에 넣은 것과 결과가 같다(테스트, 차이 0.0004 미만).
4. **말소리만 STT로**: 말소리 앞 128ms, 뒤 300ms(`speech_pad_ms`)는 그대로, 나머지는 같은 길이의 디지털 무음으로 바꿔 STT에 넣는다. 시각은 그대로 맞고, Whisper는 방 소음·숨소리를 디코딩하지 않아 지어낼 기회가 없다(faster-whisper 스트리밍도 무음은 디코딩하지 않는다). 앞 여유 때문에 STT 입력이 128ms 늦다.
5. **답변 끝**: 지원자 차례일 때 답변 끝 판정(5장)이 끝났다고 하면 그 조각이 끝나고, STT가 남은 발화를 확정하고, 허브가 답변을 닫는다(`qa.answered` → 화면이 꼬리질문 요청). 지원자가 이어 말하면 다음 조각을 같은 답에 붙이고 `qa.answered`를 더 긴 답으로 다시 보낸다(꼬리질문도 다시). 앞 조각을 STT가 마무리하는 동안 한 말은 모아 두었다가 다음 조각 앞에 넣는다(측정 중 찾은 버그, 테스트로 고정). 새 질문의 답에는 그 전 말 중 마지막 1.5초만 넣는다(질문이 기록되자마자 답하기 시작한 경우).
6. **역할 전환** (한 마이크 대면 면접): "질문 중"(Alt+1)이면 듣던 답을 닫고 그 뒤 말을 면접관 구간으로 적는다. "답변 듣는 중"(Alt+2)으로 돌아오면 그사이 말로 한 질문이 다음 질문(`question_source: interviewer`)이 되고 그 답을 듣는다. 질문을 타이핑하거나 사전 질문·꼬리질문 후보를 고르면 자동으로 답변 듣는 중이 되고, 그사이 말한 면접관 구간은 그 질문에 붙는다. 답변 끝 판정은 지원자 차례에만 한다. 질문 중으로 바꾸지 않고 면접관이 말하면 그 말이 지원자 답에 붙으므로, 한 마이크로 받을 때는 질문하기 전에 Alt+1을 누른다.
7. **감사 로그**: `audio.connected`(전송 방식, 마이크/샘플, 녹음 여부, 알림 코드), `audio.constraints`, `audio.role`, `audio.disconnected`(받은 길이), 답변마다 `transcript.listened`(또는 전사 못 함과 그 코드).

## 5. 답변 끝 판정

| 방식 (`audio.turn`) | 동작 |
| --- | --- |
| 침묵 기준 (`silence`) | 답변이 시작된 뒤(말소리 250ms 이상) `silence_ms` 동안 말이 없으면 끝 |
| Smart Turn v3 (`smart_turn`) | 말이 멈춘 지 `pause_ms`가 되면 마지막 8초를 모델에 한 번 묻는다. 점수가 `threshold` 이상이면 끝, 아니면 `max_silence_ms`까지 기다린다. 다시 말하면 처음부터 |

Smart Turn: Pipecat Smart Turn **v3.2**(Daily, **BSD-2-Clause**, Hugging Face `pipecat-ai/smart-turn-v3` 커밋 `f766f81`, 2026-01-07이 최신), CPU용 int8 ONNX `smart-turn-v3.2-cpu.onnx` **8,679,182바이트, sha256 `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`**. 관리자 화면의 다운로드로만 받고(`weights/smart-turn/v3.2-cpu/`), 실행 중에는 받지 않는다. 파일이 없으면 침묵 2초로 판정하고 `TURN-MISSING`을 띄운다. 입력은 원본 코드와 같게 만든다(마지막 8초, 앞을 0으로 채움, 평균 0·분산 1로 정규화, Whisper 80채널 로그 멜 800프레임). transformers 없이 faster-whisper의 특징 추출기를 쓴다. 이 노트북에서 한 번 판정에 약 28ms(24~34ms).

### 비교

생각하느라 멈춘 구간이 든 한국어 32건을 마이크 경로와 같은 VAD로 오프라인에서 돌렸다(`scripts/bench_turns.py`).

- FLEURS 낭독(CC BY 4.0) 24건: 한 문장 안 가장 긴 숨 쉬는 자리에 1.0~3.0초 멈춤을 넣은 것(`mid`) 8건, 같은 성별 두 문장 사이에 1.0~3.0초 멈춤(`between`) 8건, 멈춤 없는 한 문장(`single`) 8건. 멈춤은 그 녹음의 가장 조용한 구간(방 소리)으로 채웠다.
- Windows 한국어 TTS(Heami)로 만든 면접식 답변 8건(`tts`): "그때 가장 어려웠던 점은 [2.0초] 음, 팀 간 일정 조율이었습니다."처럼 문장 중간·문장 사이 멈춤 13곳.
- "조기 끊김"은 마지막 말소리 전에 답변 끝으로 본 횟수(이어 말하면 같은 답에 붙으니 다시 끊길 수 있다), "지연"은 마지막 말소리부터 끝 판정까지.

| 판정 | 문장 중간 멈춤 (mid) | 문장 사이 멈춤 (between) | 멈춤 없음 (single) | TTS 면접식 | 조기 끊김 합계 (끊긴 표본) | 끝 뒤 지연 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 침묵 1.0초 | 8 | 8 | 0 | 13 | 29 (24/32) | 1.0초 |
| 침묵 1.5초 | 7 | 6 | 0 | 10 | 23 (21/32) | 1.5초 |
| 침묵 2.0초 | 4 | 4 | 0 | 8 | 16 (16/32) | 2.0초 |
| 침묵 3.0초 | 1 | 1 | 0 | 2 | 4 (4/32) | 3.0초 |
| Smart Turn 0.2초·0.5 (Pipecat 기본) | 10 | 10 | 6 | 12 | 38 (23/32) | 평균 0.3초, 최대 3.0초 |
| Smart Turn 0.5초·0.8 | 3 | 8 | 0 | 10 | 21 (17/32) | 평균 0.6초, 최대 3.0초 |
| **Smart Turn 1.0초·0.8 (기본값)** | **2** | **8** | **0** | **9** | **19 (17/32)** | **1.0초** |
| Smart Turn 1.5초·0.8 | 3 | 6 | 0 | 9 | 18 (17/32) | 1.5초 |
| Smart Turn 2.0초·0.8 | 2 | 4 | 0 | 7 | 13 (13/32) | 2.0초 |

(Smart Turn 열의 시간은 판정 시작 침묵 `pause_ms`, 숫자는 `threshold`. 최대 침묵은 모두 3초.)

- **같은 지연이면 Smart Turn이 덜 끊는다.** 1초: 침묵 29회 → Smart Turn 19회, 1.5초: 23 → 18, 2초: 16 → 13. 차이는 거의 문장 중간 멈춤에서 난다(1초에서 8 → 2). 억양으로 "말이 덜 끝났다"를 듣는다.
- **문장을 끝내고 생각한 뒤 이어 말하는 것은 Smart Turn도 못 막는다**(between: 같은 침묵 길이와 같거나 많다). 소리로는 끝난 문장이기 때문이다. 이 경우 답이 닫혔다가 이어 붙고 꼬리질문이 다시 만들어진다.
- Pipecat 기본(0.2초 뒤 판정, 0.5)은 빠르지만 낭독의 숨 쉬는 자리도 끝으로 봐서(멈춤 없는 문장 3건에서 6회) 면접에는 너무 이르다.
- 이 숫자는 넣은 멈춤 길이(1~3초 고르게)에 따라 달라진다. 실제 면접 녹음의 멈춤 분포로 다시 재야 한다(11장).

### 기본값과 이유

- **`config/providers.yaml`(실사용 기본): Smart Turn, 판정 시작 1.0초, 기준 0.8, 최대 침묵 3초.** 같은 1초 반응에서 침묵 기준보다 조기 끊김이 3분의 1 적고(29 → 19), 침묵 2초보다 1초 빨리 닫는다. 늘어난 조기 끊김(16 → 19)은 거의 문장을 끝낸 뒤의 멈춤이라 그때까지의 답은 온전하고, 이어 말하면 같은 답에 붙어 꼬리질문이 다시 만들어진다. "1~2초 침묵에서 꼬리질문을 미리 시작하고 답변이 이어지면 버린다"는 기존 방침([model-selection.md](model-selection.md) 2장)과 같다.
- 모델 파일을 받지 않았으면 침묵 2초로 판정한다(`TURN-MISSING`). `config/providers.fake.yaml`(내려받을 것이 없는 개발·테스트 설정)도 침묵 2초다.
- 다만 이 노트북처럼 GPU 없이 Whisper를 쓰면 답이 닫히는 시점은 판정기가 아니라 STT 확정이 정한다(9장: small도 3~8초). 그래서 이 노트북에서는 두 방식의 체감 차이가 거의 없고, Smart Turn의 이점은 문장 중간에서 덜 끊는 것(꼬리질문을 반쪽 답으로 만들지 않음)이다. 반응 속도 차이가 보이는 것은 STT가 빠를 때(GPU 서버)다.

### 답변 중 미리 임베딩

꼬리질문(`ai/followups.py`)은 답변을 받으면 비식별 답변과 이미 한 질문을 임베딩해 질문 은행을 찾는다. 이 노트북의 BGE-M3로 답변 1건 int8(권장) 약 0.28초, fp32 약 0.9초다([embedding-benchmark.md](embedding-benchmark.md)). 허브가 확정 전사가 올 때마다 "지금까지의 답을 저장될 모양 그대로"(같은 비식별 문자열) 백그라운드에서 임베딩해 두고(`live/prefetch.py`), 듣기를 시작할 때 이미 한 질문도 임베딩해 둔다. `Retrieval.encode`는 텍스트로 캐시하므로 답이 닫힐 때 꼬리질문의 임베딩이 캐시에서 바로 끝난다. `ai/followups.py`는 고치지 않았다(2026-10-28 꼬리질문 지연 작업도 캐시 키인 텍스트는 그대로 둔다).

- 가드를 통과한 텍스트만 임베딩한다(꼬리질문 경로와 같다). 결과는 메모리 캐시(최대 4,096개, 모델이 바뀌면 비움)에만 있고 저장하지 않는다.
- 최신 텍스트만 임베딩한다(기다리던 것은 새것으로 바뀐다). 답이 닫힐 때 마지막 임베딩이 아직 돌고 있으면 꼬리질문은 그 결과를 기다린다(`Retrieval.encode`가 진행 중인 같은 텍스트를 공유, 2026-10-28. 그 전에는 한 번 더 임베딩했다).

## 6. 오류 코드

화면에 코드와 설명이 함께 나온다. 사내에서 문제가 나면 코드만 옮겨 적어 오면 된다. "멈춤"은 마이크가 꺼지는 것, "계속"은 일부만 안 되고 나머지는 도는 것.

| 코드 | 어디서 | 뜻 | 처리 |
| --- | --- | --- | --- |
| `MIC-HTTPS` | 브라우저 | HTTPS(또는 localhost)가 아니라 브라우저가 마이크와 AudioWorklet을 막음(진단용 샘플도) | 멈춤. 사내 TLS 인증서로 https 주소를 쓴다 |
| `MIC-DENIED` | 브라우저 | 마이크 권한 거부(사용자 또는 회사 정책) | 멈춤. 주소창에서 허용, 정책이면 담당 부서 |
| `MIC-NONE` | 브라우저 | 마이크 장치 없음 | 멈춤. 연결·OS 입력 장치 확인 |
| `MIC-BUSY` | 브라우저 | 다른 프로그램이 쓰는 중이거나 장치를 열 수 없음 | 멈춤 |
| `MIC-UNSUPPORTED` | 브라우저 | getUserMedia·AudioWorklet 미지원 | 멈춤. 최신 Chrome·Edge |
| `MIC-FAILED` | 브라우저 | 그 밖의 마이크 오류 | 멈춤 |
| `SAMPLE-FAILED` | 브라우저 | 진단용 샘플을 불러오지 못함 | 멈춤 |
| `WS-BLOCKED` | 브라우저 | WebSocket이 열리지 않음(프록시·DLP) | 계속. HTTP 청크로 보냄 |
| `WS-LOST` | 브라우저 | 쓰던 WebSocket이 끊김 | 계속. HTTP 청크로 이어 보냄 |
| `HTTP-FAILED` | 브라우저 | WebSocket·HTTP 모두 실패 | 멈춤. 네트워크·프록시 |
| `NO-CONSENT` | 서버 | 녹음 동의가 없는 면접 | 멈춤. 수기 모드 |
| `NOT-LIVE` | 서버 | 진행 중인 면접이 아님(끝났거나 시작 전) | 멈춤 |
| `MIC-TAKEN` | 서버 | 다른 창·기기가 이 면접의 마이크를 보내는 중(10초 조용하면 넘겨받음) | 멈춤 |
| `AUDIO-FORMAT` | 서버 | 16kHz 모노 16비트 PCM이 아님, 첫 메시지 오류, 조각이 5초 넘음 | 멈춤 |
| `VAD-MISSING` | 서버 | VAD를 쓸 수 없음(faster-whisper·onnxruntime 없음, 모델 sha256 다름) | 계속. 녹음만 하고 전사 안 함, 수기 답변 |
| `TURN-MISSING` | 서버 | Smart Turn 파일 없음 | 계속. 침묵 2초로 판정 |
| `DENOISE-MISSING` | 서버 | 고른 서버 잡음 억제를 쓸 수 없음(pyrnnoise·DeepFilterNet3 파일 없음, 라이브러리 sha256 다름) | 계속. 잡음 억제 없이 전사 |
| `STT-MISSING` | 서버 | 실시간 STT를 만들 수 없음(가중치·패키지 없음) | 계속. 녹음만, 수기 답변 |
| `STT-FORMAT` | 서버 | 실시간 STT가 PCM을 못 읽음 | 계속. 녹음만, 수기 답변 |
| `STT-FAILED` | 서버 | 전사 중 오류 | 계속. 수기 답변 |
| `REC-FAILED` | 서버 | 녹음 파일을 못 씀(디스크·권한) | 계속. 전사는 계속, 녹음 안 됨 |
| `MOCK-API` | 모의 API | 백엔드 없이 띄운 화면(`npm run dev`) | 멈춤. `npm run dev:api`에서 쓴다 |

서버 코드는 `src/interview_assistant/live/codes.py`, 브라우저 코드와 설명은 `frontend/src/features/interview/audio/errors.ts`. WebSocket이 거절하면 `{"type":"error","code",…}`를 보내고 4000 + HTTP 상태로 닫는다(닫힘 이유 = 코드). 전사를 못 하는 이유는 전사 스트림 `status.error`와 `status.mic.notices`로도 온다.

## 7. 서버 잡음 억제

관리자 > 모델 설정 > 서버 잡음 억제(`audio.denoise`)에서 고른다. **기본은 끔**이고, 소음 섞은 한국어로 잰 결과 켤 근거가 나오지 않았다(7.4).

| 고를 수 있는 것 | 무엇 | 지연 | CPU (음성 1초당, 이 노트북) |
| --- | --- | ---: | ---: |
| 끔 (기본) | 브라우저가 보낸 소리 그대로 | 0 | 0 |
| RNNoise | Xiph의 작은 RNN. 10ms 프레임마다 대역 이득 | 35ms | 0.05~0.22초 |
| DeepFilterNet3 | 대역 이득 + 4.8kHz 아래 5탭 딥 필터, 앞보기 20ms | 45ms | 0.16~0.37초 (앞 문맥 300ms) |

### 7.1 어떻게 붙였나

- **자리**: 마이크 경로에서 녹음 다음, VAD 앞(4장 2번). 녹음은 원음 그대로라 면접 뒤 재전사(8장)는 잡음 억제를 거치지 않는다. VAD·STT·답변 끝 판정이 모두 억제된(조금 늦은) 소리를 듣는다.
- **마이크마다 상태**: provider는 면접끼리 공유되므로 `DenoiseProvider.stream()`이 마이크마다 따로 상태(필터, 모델 기억, 덜 찬 프레임)를 만든다(`providers/base.py` `DenoiseStream`). 조각 크기가 어떻든 같은 길이를 돌려주고, 출력은 정해진 만큼(`delay_samples`) 늦다. 처음 그만큼은 디지털 무음이다. 조각을 어떻게 나눠 넣어도 결과가 같다(RNNoise는 바이트까지, 테스트 `tests/test_denoise.py`).
- **16kHz ↔ 48kHz**: 두 모델 모두 48kHz용이다. 서버가 받는 것은 16kHz라(브라우저가 내림) 서버에서 48kHz로 올려 걸고 다시 내린다(`providers/denoise/resample.py`: 241탭 Kaiser FIR, 7.5kHz 차단, 8.2kHz부터 약 80dB, 왕복 5ms). 모델은 8kHz 위가 빈 소리를 본다. 브라우저 48kHz 단계에서 거는 쪽은 브라우저에 모델을 넣어야 해서 하지 않았다.
- **RNNoise**: pyrnnoise 0.4.5 휠 안의 라이브러리(xiph/rnnoise `70f1d25`, 2025-02, v0.2 뒤, 모델 포함 14.8MB)만 ctypes로 연다. 크기·sha256을 플랫폼마다 고정해 불러올 때 확인한다(Silero VAD와 같은 방식). 파이썬 모듈과 그 의존성(matplotlib, audiolab)은 쓰지 않는다([reference/libraries.md](reference/libraries.md) 5장). 출력이 입력보다 20ms 늦다(측정). 이 지연과 덜 찬 프레임 10ms, 필터 5ms를 더해 35ms다. 다운로드할 것이 없다.
- **DeepFilterNet3**: 공식 패키지는 PyTorch와 `numpy<2`를, DSP 바인딩 deepfilterlib은 Python 3.11까지의 휠을 요구해 쓰지 않는다. 대신 공식 v0.5.6 체크포인트를 네트워크만 ONNX로 내보낸 파일(Hugging Face `soniqo/DeepFilterNet3-ONNX` 커밋 `63d8ba4`, MIT, `deepfilter.onnx` **8,608,859바이트, sha256 `e1157049059434ae0d5857e32c812abea227b975e946b2eb64d001abbce156d3`**)을 관리자 다운로드로 받아 ONNX Runtime으로 돌린다(`weights/deepfilternet/dfn3-onnx/`). STFT(960점 Vorbis 창, 480 hop), ERB 32대역 특징과 평균 정규화, 저역 96빈 복소 특징과 단위 정규화, 대역 이득, 잡음 섞인 스펙트럼에 거는 5탭 딥 필터, 중첩 합성은 libDF 소스대로 NumPy로 짰다(`providers/denoise/deepfilternet.py`). ERB 대역 폭과 창은 그 저장소가 공개한 상수와 같고, 녹음 전체를 한 번에 처리한 결과(`enhance`, 원본의 `df.enhance`와 같은 방식)와 스트림은 1 LSB 안에서 같다(테스트).
- **DeepFilterNet3 스트리밍**: 내보낸 그래프는 호출 사이에 GRU 상태를 넘기지 못한다(매번 0에서 시작). 그래서 새 프레임마다 `앞 문맥`(기본 300ms)만큼 지난 프레임을 함께 다시 넣고 새 프레임 출력만 쓴다. 앞 문맥에 따른 차이와 비용은 7.3의 마지막 표에 있다. 네트워크는 앞보기 2프레임이 들어온 새 프레임이 있을 때마다 한 번 돈다(브라우저 100ms 조각이면 조각마다 한 번). 지연 45ms = 앞보기 20ms + 덜 찬 프레임 10ms + STFT 10ms + 필터 5ms.
- **최대 억제**(`atten_lim_db`, 두 모델 공통, 기본 0 = 제한 없음): 원래 소리를 그만큼 낮춰 섞어, 잡음을 그 이상 줄이지 않는 대신 변형을 덜 한다(DeepFilterNet의 `atten_lim_db`와 같은 계산).
- **쓸 수 없을 때**: 고른 억제기를 불러오지 못하면(패키지·파일 없음, sha256 다름) 끄고 전사하며 `DENOISE-MISSING`을 띄운다(6장).
- **연결 테스트**: 샘플(또는 올린 녹음)을 100ms 조각으로 넣어 지연, 음성 1초당 처리 시간, 말소리 구간과 그 밖의 소리 크기 변화(Silero VAD로 나눔)를 보여 준다.
- **설치**: `uv sync --extra … --extra denoise`([setup.md](setup.md)). 사내 반입에는 pyrnnoise 휠과 `weights/deepfilternet/dfn3-onnx/`(`.complete.json` 포함)를 넣는다(10장).

### 7.2 측정 방법

`scripts/bench_denoise.py`, 2026-10-31 ~ 11-01, 이 노트북(i7-1360P, 배터리 사용 중이라 속도는 흔들린다). 아직 실제 면접 녹음이 없어 깨끗한 한국어 낭독에 소음을 섞었다.

- **말소리**: `answer-pauses`(진단용 마이크 샘플, 두 화자, 생각하는 멈춤 1.5·1.9초)와 FLEURS 한국어 test 3건(CC BY 4.0, [whisper-benchmark.md](whisper-benchmark.md)와 같은 출처). large-v3는 시간 때문에 `answer-pauses`와 FLEURS 2건, 10·5dB만.
- **소음** (Wikimedia Commons, 라이선스 확인, 합계 17MB, 측정에만 쓰고 저장소에 넣지 않음):

| 이름 | 파일 | 라이선스 | 내용 |
| --- | --- | --- | --- |
| office | Open-space office ambiance.ogg | CC BY-SA 4.0, Mooeypoo | 개방형 사무실(여럿이 말하는 소리, 전화, 키보드) |
| aircon | Air conditioner hum (Gravity Sound).wav | CC BY 4.0, Gravity Sound | 에어컨 웅웅거림 |
| fan | Fan (Gravity Sound).wav | CC BY 4.0, Gravity Sound | 선풍기 |
| keyboard | Laptop keyboard.ogg | 퍼블릭 도메인, russiandoll | 노트북 키보드 타이핑 |

- **섞기**: 소음 1초 + 말소리(아래에 소음) + 소음 4초. SNR 20·10·5dB(large-v3는 10·5dB)는 깨끗한 말소리의 말소리 프레임(Silero VAD) 평균 세기 대비. 소음은 녹음의 임의 지점부터. `answer-pauses`의 둘째 문장은 화자가 작아 실제 SNR이 표시보다 낮다.
- **처리**: 표본마다 새 스트림에 100ms 조각으로 넣고 지연만큼 당겨 맞춘다.
- **STT**: Whisper small은 실시간 경로대로(Silero VAD → 말소리와 앞 128ms·뒤 300ms만 남기고 무음 → `stream`, beam 1의 확정 전사). Whisper large-v3는 면접 뒤 재전사대로(`transcribe`, beam 5, VAD). 제품은 재전사에 원음 녹음을 쓰므로 large-v3 열은 "재전사 전에 억제하면 나아지나"를 본다.
- **지표**: CER(공백·문장부호 제외, 표본의 편집 수 합 ÷ 글자 수 합). VAD: 소음만 있는 앞뒤 구간에서 말로 본 시간(분당 초), 깨끗한 말소리 프레임 중 여전히 말로 들은 비율. 답변 끝(Smart Turn 1초·0.8·최대 3초): 마지막 말소리 뒤 4초 안에 닫혔는지, 닫히기까지 걸린 시간, 마지막 말소리 전에 닫은 횟수(조기 끊김).

### 7.3 결과

**Whisper small, 실시간 경로** (표본 4개 × 소음 4종, CER):

| 억제 | 깨끗 | 20dB | 10dB | 5dB |
| --- | ---: | ---: | ---: | ---: |
| 끔 | 3.9% | 11.9% | 20.2% | 23.3% |
| RNNoise | 3.9% | 10.6% | 18.4% | 25.0% |
| DeepFilterNet3 | 3.9% | 12.6% | 21.9% | 28.2% |

| 표본 (소음 섞은 것만) | 끔 | RNNoise | DeepFilterNet3 |
| --- | ---: | ---: | ---: |
| answer-pauses (둘째 화자 목소리가 작다) | 39.0% | 34.7% | 40.0% |
| FLEURS 1883 | 8.3% | 10.4% | 11.0% |
| FLEURS 1929 | 3.5% | 5.5% | 6.1% |
| FLEURS 1701 | 6.1% | 7.3% | 11.1% |
| 소음 섞은 48건 중 끔보다 2%p 넘게 나음 / 나쁨 | | 7 / 13 | 4 / 22 |

| 억제 (SNR 합침) | office | aircon | fan | keyboard |
| --- | ---: | ---: | ---: | ---: |
| 끔 | 16.7% | 22.7% | 20.7% | 13.8% |
| RNNoise | 16.4% | 26.4% | 20.4% | **8.7%** |
| DeepFilterNet3 | 19.7% | 26.6% | 22.0% | 15.3% |

**Whisper large-v3, 재전사 경로** (표본 3개, 10·5dB):

| 억제 | 깨끗 | 10dB | 5dB | 소음 섞은 24건 중 나음 / 나쁨 |
| --- | ---: | ---: | ---: | ---: |
| 끔 | 19.4% | 20.0% | 20.9% | |
| RNNoise | 2.9% | 18.1% | 22.6% | 2 / 10 |
| DeepFilterNet3 | 7.6% | 21.6% | 22.2% | 1 / 10 |

- large-v3의 "깨끗 19.4%"는 한 가지 일이다. 깨끗한 `answer-pauses`에서 large-v3가 둘째 문장을 통째로 빠뜨렸다. 저장소의 원본 파일 그대로, VAD를 끄고 디코딩해도 같아서 디코더의 문제이고 억제와는 상관없다. 억제한 소리에서는 우연히 둘째 문장이 나왔다. FLEURS 표본만 보면 억제가 같거나 나빴다(1883: 5.7 → 6.6·5.9%, 1929: 5.2 → 7.9·8.5%).
- 지어낸 문장: 끔에서는 0건이었다. 억제하면 large-v3가 소음만 있는 뒤쪽에 두 번 문장을 붙였다(DeepFilterNet3 "자막 제공 배달의민족", RNNoise 1건). small은 DeepFilterNet3에서 1건.

**VAD와 답변 끝** (small 측정의 소음 섞은 48건, Smart Turn 1초·0.8·최대 3초):

| 억제 | 잡음을 말로 봄 | 말소리 유지 | 답변 닫힘 (끝 뒤 4초 안) | 닫히기까지 평균 | 조기 끊김 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 끔 | 분당 0.2초 | 90.7% | 39/48 | 1.14초 | 14 |
| RNNoise | 분당 0.1초 | 92.8% | 44/48 | 1.17초 | 12 |
| DeepFilterNet3 | 분당 0.0초 | 91.0% | 43/48 | 1.12초 | 15 |

- Silero VAD는 억제가 없어도 이 소음들을 거의 말로 보지 않았다. 소음이 하는 일은 작은 목소리를 가리는 것이다. 닫히지 않은 답과 조기 끊김은 거의 `answer-pauses`의 둘째 화자를 VAD가 못 들은 경우다. VAD가 그 화자를 놓치면 답이 그 앞에서 닫혀 조기 끊김으로 세었다. RNNoise는 그 일부를 되살렸다(키보드 소음에서 특히). 판정 자체의 지연은 거의 같다.

**처리 시간과 지연** (60초, 100ms 조각, 한 스레드):

| 억제 | 지연 | 음성 1초당 처리 시간 |
| --- | ---: | ---: |
| RNNoise | 35ms | 0.22초 |
| DeepFilterNet3 (앞 문맥 300ms) | 45ms | 0.37초 |

| DeepFilterNet3 앞 문맥 | 녹음 전체를 한 번에 처리한 것과의 차이 (SNR, 높을수록 가깝다) | 음성 1초당 처리 시간 |
| ---: | ---: | ---: |
| 0ms | 6.2dB | 0.16초 |
| 100ms | 13.6dB | 0.23초 |
| 200ms | 19.1dB | 0.30초 |
| **300ms (기본)** | **23.9dB** | **0.37초** |
| 500ms | 25.4dB | 0.51초 |
| 1,000ms | 25.9dB | 0.86초 |

- 처리 시간은 배터리가 30%대로 내려가 전력이 제한된 뒤에 쟀다. 같은 세션 앞쪽(배터리 60%대)에서는 RNNoise가 0.05~0.11초, DeepFilterNet3(앞 문맥 500ms)가 0.16초였다. 절대값보다 비율로 읽는다. 억제는 마이크마다 이벤트 루프에서 조각마다 돈다(Silero VAD처럼). 켜면 면접 하나당 이만큼 CPU가 더 든다.
- 앞 문맥 300ms가 넘으면 결과는 거의 그대로인데 처리 시간은 계속 는다. 그래서 기본을 300ms로 했다.

### 7.4 언제 켜나

- **기본은 끔 그대로 둔다.** 이 측정으로는 바꿀 근거가 없다. 말소리가 잘 들리는 FLEURS 표본에서는 두 억제기 모두 small과 large-v3의 CER을 올렸다(표본 5개 모두). 소음 섞은 표본 하나하나를 끔과 비교하면 나빠진 경우가 나아진 경우보다 많다(small RNNoise 7 대 13, DeepFilterNet3 4 대 22).
- **DeepFilterNet3는 켜지 않는다.** 모든 SNR에서 끔보다 나빴다(small 5dB 23.3 → 28.2%). 듣기에는 가장 깨끗하지만 그 변형이 Whisper를 더 틀리게 한다. 연구들이 말한 그대로다([reference/audio-quality.md](reference/audio-quality.md) 7장).
- **RNNoise가 도움이 된 경우는 하나다.** 키보드처럼 짧게 튀는 소음이 마이크 가까이 있어 VAD가 작은 목소리를 놓칠 때다. 키보드 소음에서 small CER이 10dB 18.2 → 9.4%, 5dB 19.2 → 11.8%로 낮아졌다. 반대로 꾸준한 소음에는 나빴다(에어컨 5dB 27.6 → 38.4%). 그런 방이 실제로 있으면 순서는 이렇다.
  1. 마이크를 지원자 가까이, 키보드에서 멀리 둔다.
  2. VAD 말소리 기준을 낮춰 본다(관리자 > 음성 구간, 0.5 → 0.4 안팎). 이번에는 재지 않았다.
  3. 그래도 VAD가 답을 놓치면 그 방의 녹음으로 끔과 RNNoise를 같은 방식으로 비교하고, 나아질 때만 켠다.
- **재전사(large-v3)는 지금처럼 원음으로 한다.** 억제한 소리로 재전사해도 나아지지 않았고, 지어낸 문장이 생겼다.
- 브라우저 NS도 같은 이유로 끔을 유지한다(2장).
- **이 측정의 한계**: 낭독에 녹음된 소음을 더했을 뿐이다. 방의 울림, 실제 마이크 거리, 대화체, 면접 용어는 없다. 표본은 small 4개, large-v3 3개다. 실제 면접 녹음이 생기면 다시 잰다(11장).

다시 재기 (Whisper small·large-v3, Smart Turn, DeepFilterNet3 파일을 받아 둔 뒤. FLEURS 폴더는 [whisper-benchmark.md](whisper-benchmark.md)·5장과 같은 `manifest.json` 형식):

```bash
uv run python scripts/bench_denoise.py --fetch-noise noise/
uv run python scripts/bench_denoise.py --fleurs <FLEURS 폴더> --noise noise/ --clips 4 --models small --json small.json
uv run python scripts/bench_denoise.py --fleurs <FLEURS 폴더> --noise noise/ --clips 3 --large-clips 3 --snrs 10 5 --models large-v3 --json large.json
uv run python scripts/bench_denoise.py --cpu --noise noise/
```

실제 면접 녹음이 생기면 같은 비교를 그 녹음(동의 받은 것 20건 이상, 소음 있는 방 포함)과 브라우저 NS 켬·끔으로 다시 한다(11장).

## 8. GPU가 없을 때: 실시간은 작게, 기록은 크게

이 노트북(GPU 없음)에서는 정확한 모델이 실시간을 못 따라가고(medium 발화 끝 → 확정 약 8~12초), 빠른 모델은 자주 틀린다(small CER 13%).

- **관리자 > 모델 설정 > STT 사후 > "면접 뒤 녹음 재전사"**를 켜면, 면접이 끝난 뒤 녹음(동의한 면접만)을 STT 사후 모델로 다시 전사해 실시간 전사와 따로 저장한다(`transcript_segments.source = batch`, Alembic 0008). 그래서 "STT 실시간 = Whisper small, STT 사후 = large-v3 + 재전사 켬"으로 나눌 수 있다. large-v3는 이 노트북에서 녹음 길이의 약 1.2배 걸린다(30초 녹음에 약 36초).
- 저장 전에 비식별화한다. 시각은 녹음 안의 위치이고, 화자는 마이크의 역할 기록(질문 중 / 답변 듣는 중)으로 붙인다(서버가 그사이 다시 켜졌으면 모두 지원자). 결과는 `GET /api/sessions/{id}/transcript?source=batch`, 감사 로그 `transcript.retranscribed`(구간 수, 녹음 길이, 걸린 시간).
- 하지 않은 것: 재전사 결과를 질문별로 나누기, AI 채점이 재전사 결과를 읽기(지금은 실시간 답변을 읽는다), 화면에서 보기·비교, 수동 "재전사" 버튼. 녹음 시각과 질문 시각을 맞추는 일이 먼저라 범위에서 뺐다.

## 9. 측정

2026-10-28 · `scripts/bench_live_audio.py`. 이 노트북(i7-1360P, RAM 16GB, GPU 없음, 전원 연결·충전 100%). 앱의 실제 조각을 한 프로세스에서 돌렸다: 시드 DB, 전사 허브, `MicrophoneSource`(Silero VAD + 답변 끝 판정), 로컬 Whisper(STT 실시간, beam 1), 비식별화, 꼬리질문 스트림(fake LLM 지연 없음, fake 임베딩). 표본 WAV를 100ms 조각으로 실제 시간에 맞춰 넣고, 답이 닫히면 화면처럼 바로 꼬리질문을 요청했다. 시간은 표본의 마지막 말소리(VAD 기준)부터.

| STT | 답변 끝 판정 | 끝 판정까지 | 최종 전사까지 | 답변 닫힘까지 (평균, 범위) | 첫 꼬리질문 카드까지 |
| --- | --- | ---: | ---: | ---: | ---: |
| Whisper small | 침묵 2초 | 1.9~2.0초 | 3.0~7.3초 | **5.2초** (3.0~7.3) | 닫힘 + 0.03초 |
| Whisper small | Smart Turn 1초·0.8 | 1.2~1.9초 | 5.4~8.4초 | **6.7초** (5.4~8.5) | 닫힘 + 0.03초 |
| Whisper medium | 침묵 2초 | 1.9~2.0초 (이어 붙은 조각은 14초) | 11.0~23.4초 | **17.0초** (11.0~23.4) | 닫힘 + 0.03초 |
| Whisper medium | Smart Turn 1초·0.8 | 1.2~1.3초 (이어 붙은 조각은 10~20초) | 11.8~29.5초 | **19.7초** (11.8~29.6) | 닫힘 + 0.03초 |

표본 4개(각 설정 같음): `answer-pauses`(16.6초, 멈춤 1.5·1.9초), `ko-fleurs-1894`(11.5초), TTS 면접식 답변(멈춤 1.5·1.0·2.2초), FLEURS 문장 중간 멈춤(1.5초). 원자료는 스크립트를 다시 돌리면 나온다(`--json`).

- **이 노트북에서는 답이 닫히는 때를 STT가 정한다.** 판정기는 말 끝 1~2초 뒤에 끝을 알리지만, Whisper가 마지막 발화를 확정하는 데 small 3~8초, medium 11초 이상 걸린다(30초 창 고정 비용, 디코딩 중인 부분 전사를 기다림). 판정기 차이(침묵 2초 vs Smart Turn 1~1.9초)는 이 시간에 묻혔고, 평균 차이(5.2 vs 6.7초)는 표본 4개의 디코딩 타이밍 차이 안이다.
- **medium은 실시간을 못 따라간다.** 디코딩이 말보다 느려 뒤로 밀리고, 답이 일찍 닫혔다 이어 붙으면 앞 조각을 다 마무리한 뒤에야 다음 조각을 시작해 더 늦어진다(30초 가까이). 이 노트북에서 실시간은 small이고, 정확한 기록은 면접 뒤 재전사(8장)로 남긴다. GPU가 있으면 다시 잰다.
- **답이 닫힌 뒤 첫 카드까지는 0.03초**(fake LLM, fake 임베딩). 실제로는 여기에 LLM 첫 토큰 시간이 더해지고, 질문 은행 후보는 BGE-M3 답변 임베딩(int8 약 0.28초, fp32 약 0.9초) 뒤에 뜨는데, 답변 중 미리 임베딩(5장)으로 이 시간이 대부분 빠진다.
- 측정 중 찾은 문제: 답이 일찍 닫혔다 이어질 때 앞 조각을 STT가 마무리하는 동안 한 말이 사라졌다(320ms만 남김). 다음 조각에 모두 넣게 고치고 테스트를 더했다.
- 판정기 자체 시간: Smart Turn 한 번 약 28ms(24~34ms), Silero VAD는 100ms 조각에 1ms 안팎.

다시 재기 (Whisper small·medium과 Smart Turn 파일을 받아 둔 뒤):

```bash
uv run python scripts/bench_live_audio.py --sizes small medium --turns silence smart_turn --json live.json
uv run python scripts/bench_turns.py --build-fleurs <FLEURS 폴더> --out turns/ && uv run python scripts/bench_turns.py --samples turns/
```

## 10. 사내 환경에 따라 바꿀 것

| 확인할 것 ([internal-environment-checklist.md](internal-environment-checklist.md)) | 이렇게 되면 | 바꿀 것 |
| --- | --- | --- |
| 사내 HTTPS | http로만 열림 | 마이크가 안 열린다(`MIC-HTTPS`). 사내 인증서로 HTTPS를 붙이는 것 말고는 방법이 없다. localhost는 예외라 서버 PC에서 직접 열면 된다 |
| 면접실 PC 마이크 허용 | 정책으로 막힘 | `MIC-DENIED`. 브라우저 정책(Chrome `AudioCaptureAllowedUrls`)에 이 시스템 주소를 넣어 달라고 요청. 그전까지 진단용 샘플로 나머지 경로를 확인 |
| DLP·프록시의 WebSocket | 막힘 | 자동으로 HTTP 청크로 보낸다(`WS-BLOCKED`). 요청이 100ms~4초마다 하나씩이라 프록시 요청 수 제한·본문 검사를 확인. HTTP도 막히면 `HTTP-FAILED` |
| GPU | 없음 | STT 실시간 small + STT 사후 large-v3·재전사 켬(8장). 있으면 Whisper를 GPU로(provider에 device 옵션 추가 필요) 돌리고 실시간 medium 이상 |
| GPU | 있음, 실시간이 빠름 | 답변 끝 판정의 차이가 그대로 체감된다. Smart Turn 판정 시작을 0.5~1초에서 조정 |
| 인터넷 차단 | 관리자 다운로드 안 됨 | Smart Turn 파일(8.7MB)과 Whisper 가중치를 반입 꾸러미에 넣어 `IA_WEIGHTS_DIR`에 두고 `.complete.json`까지 함께(크기·sha256은 5장, `providers/weights.py`). Silero VAD는 faster-whisper 패키지 안에, RNNoise는 pyrnnoise 휠 안에 있어 따로 없다. DeepFilterNet3를 쓸 경우에만 `weights/deepfilternet/dfn3-onnx/`(8.6MB, 7장)도 |
| 면접실 마이크 | 한 개(대면) | 질문 중 / 답변 듣는 중 전환(Alt+1/Alt+2)을 면접관에게 안내 |
| 면접실 마이크 | 지원자용 따로 | 지원자 마이크를 이 화면에 연결하고 질문은 타이핑·선택(전환 불필요). 한 세션에 마이크 두 개는 아직 안 된다 |
| 소음 많은 방 | VAD가 잡음을 말로 봄 | 관리자 > 음성 구간 > 말소리 기준을 0.6~0.7로 |
| 소음 많은 방 | 작은 목소리를 VAD가 놓침(답이 일찍 닫힘) | 마이크를 지원자 가까이, 말소리 기준을 0.4 안팎으로. 키보드 소음이면 그 방 녹음으로 RNNoise를 비교(7.4) |
| 브라우저 | 잡음 억제가 꼭 필요 | 마이크 설정에서 NS를 켜고 같은 방 녹음으로 CER을 비교 |

## 11. 남은 것

- 실제 면접 녹음(동의 받은 것)으로 답변 끝 판정 다시 재기: 멈춤 분포, 조기 끊김, Smart Turn 한국어 실제 음성 정확도.
- 비대면 면접(WebRTC 참가자 트랙), 한 세션에 마이크 두 개, 대면 화자분리.
- 재전사 결과를 질문별로 나누고 채점에 쓰기, 화면에서 보기, 재전사 버튼.
- 실제 면접 녹음으로 서버 잡음 억제(7장)를 다시 재기, 브라우저 NS·AGC 켬·끔 CER 비교, VAD 말소리 기준을 낮췄을 때 작은 목소리 놓침 비교.
- DeepFilterNet3를 정확히 스트리밍하기: GRU 상태를 입출력으로 낸 ONNX가 있으면 앞 문맥을 다시 넣지 않아도 된다(지금은 근사, 7.1).
- 실제 마이크로 확인(Chrome에서 사람 목소리): 이번에는 미리보기 브라우저가 마이크를 막아 진단용 샘플로만 확인했다.
- 여러 서버 인스턴스: 마이크 상태가 프로세스 메모리에 있어 WebSocket과 전사 스트림이 같은 인스턴스에 붙어야 한다.
- GPU에서 Whisper 실시간(provider에 device 옵션).
