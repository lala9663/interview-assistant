# 화자분리 비교

2026-10-27 · 녹음에서 "누가 언제 말했나"를 나누는 방법. 면접 방식별 권장은 [model-selection.md](../model-selection.md) 4장에 있고, 여기는 그 배경 비교다. 마이크·에코는 [audio-quality.md](audio-quality.md).

## 1. 이 프로젝트에 필요한 것

- 면접은 **지원자 1명 + 면접관 여러 명**이다. 전사의 화자는 "면접관 / 지원자" 두 가지뿐이다(그룹 면접은 범위 밖). 그래서 일반적인 화자분리(몇 명인지 모르는 사람들을 모두 나누기)보다 쉬운 문제, 즉 "이 구간이 지원자인가"만 맞히면 된다.
- 면접관 질문은 면접관이 앱에서 기록한다. 질문 구간은 이미 안다.
- 화자분리는 `화자1`, `화자2`처럼 이름 없이 나눌 뿐이다. 누가 지원자인지는 따로 잇는다(면접관이 화면에서 지정하거나, 지원자 마이크와 비교).
- 틀리면 면접관 말이 지원자 답변으로 채점되거나 지원자 말이 빠진다([audio-quality.md](audio-quality.md) 9장).

## 2. 모델 없이 나누기 (먼저 권함)

| 상황 | 방법 | 장점 | 주의 |
| --- | --- | --- | --- |
| 비대면 (WebRTC) | 참가자마다 오는 오디오 트랙 = 사람 | 정확하고 실시간, 계산 없음 | 지원자 쪽 에코로 면접관 목소리가 지원자 트랙에 섞일 수 있다. 브라우저 에코 제거와 이어폰 |
| 대면, 사람마다 마이크 | 채널 = 사람 (다채널 오디오 장비) | 가장 정확, 실시간 | 장비가 필요하다. 옆 사람 목소리가 내 마이크에도 들어간다(누화) |
| 대면, 지원자 마이크 + 면접관 쪽 마이크 하나 | 같은 시각 두 마이크의 소리 크기를 비교해 지원자 마이크가 충분히 크면 지원자 구간 | 단순한 규칙, CPU 거의 안 씀, 실시간 | 겹쳐 말하는 구간은 둘 다로 둔다. 기준 차이(dB)는 방마다 재서 정한다 |
| 대면, 지원자 마이크 하나 | 지원자 마이크만 전사, 면접관 질문은 앱 기록 | 장비 최소 | 면접관 목소리가 지원자 마이크에 섞이면 거를 방법이 없다. 지향성 마이크로 줄인다 |
| 대면, 방 마이크 하나 | 화자분리 모델 필요 (3·4장) | 장비 최소 | 실시간은 부정확. 사후 전사에서 하고 사람이 고친다 |

## 3. 오픈 모델

DER(화자분리 오류율) = (놓친 말 + 말이 아닌데 말로 본 것 + 화자 혼동) ÷ 전체 말 시간. 경계 앞뒤 여유(collar)를 주면 낮게 나온다. pyannote 표는 여유 없이, 겹쳐 말하기 포함("Full")이다. 표마다 조건이 달라 숫자를 그대로 비교하면 안 된다. 방 마이크 하나 상황에 가장 가까운 공개 데이터는 AMI SDM(회의실 원거리 마이크 하나)이다.

| 모델 | 라이선스 (코드 / 가중치) | 실시간 | 화자 수 | 공개 DER (AMI SDM 등) | CPU | 상업 |
| --- | --- | --- | --- | --- | --- | --- |
| pyannote speaker-diarization-3.1 | MIT / MIT, Hugging Face 약관 동의 필요 | 아니오 (파일 단위) | 제한 없음 | AMI SDM 22.7, DIHARD3 21.4, VoxConverse 11.2 | 기본 CPU로 돈다. 속도는 확인 필요 | 가능 |
| pyannote speaker-diarization-community-1 | MIT / CC-BY-4.0, 약관 동의 필요 | 아니오 | 제한 없음 | AMI SDM 19.9, DIHARD3 20.2, VoxConverse 11.2. H100에서 1시간 음성에 31초 | 같음 | 가능 (출처 표시) |
| diart (pyannote 모델로 스트리밍) | MIT / pyannote 모델 약관 | 예, 지연 0.5~5초 조절 | 제한 없음 | 확인 필요 | 5초 조각 분할에 CPU 12ms (README) | 가능 |
| NVIDIA Streaming Sortformer v2 | Apache-2.0 (NeMo) / CC-BY-4.0 | 예, 지연 0.32~30.4초 | 최대 4 | DIHARD3 19.68(30.4초)~20.19(0.32초) | 공식 언급 없음. C++ 실행기·GGUF 147MB가 있다 | 가능 |
| NVIDIA Streaming Sortformer v2.1 | Apache-2.0 / NVIDIA Open Model License | 예 | 최대 4 | AMI SDM 17.80(30.4초)·20.57(1.04초) | 같음 | 라이선스 조건 확인 |
| NVIDIA Nemotron-3-Diarization (2026-09) | Apache-2.0 / OpenMDW-1.1 | 예, 스트리밍·파일 한 모델 | 최대 8 | AMI SDM 11.14(30.4초)·12.95(0.32초), DIHARD3 12.73 | NVIDIA GPU(Ampere 이상) 필요 | 가능 |
| NVIDIA Sortformer v1 | Apache-2.0 / CC-BY-NC-4.0 | 아니오 | 최대 4 | DIHARD3 16.28 (4명 이하) | | **불가 (비상업)** |
| NVIDIA MSDD telephonic | Apache-2.0 / NGC 약관 | 아니오 | | 전화 음성 전용, 2023년 이후 갱신 없음 | | 약관 확인 |
| WhisperX | BSD-2-Clause / pyannote community-1 | 아니오 | | pyannote와 같음. README가 겹쳐 말하기에 약하다고 적음 | | 가능 |
| DiariZen | MIT / CC BY-NC 4.0 | 아니오 | | AMI SDM 13.9, DIHARD3 14.5 | | **불가 (비상업)** |
| 3D-Speaker | Apache-2.0 / 확인 필요 | 아니오 | | AMI SDM 21.76 (조건 확인 필요) | | 가중치 확인 필요 |
| Picovoice Falcon | Apache-2.0 / 온라인 AccessKey 필요 | | | 확인 필요 | 기기 안에서 돈다 | 유료, 가격 비공개 |

- **한국어 평가가 없다.** 위 숫자는 영어·중국어 회의 데이터다. 한국어로 찾은 것은 유아 대화 53건 연구 하나뿐이다(Sortformer DER 33%, 조건 불명). 실제 대면 면접 녹음으로 재야 한다.
- WhisperX는 전사 + 단어 시각 맞추기 + pyannote 화자분리를 묶은 도구다. 한국어 단어 시각 모델(kresnik/wav2vec2-large-xlsr-korean, Apache-2.0)이 기본 목록에 있어, 사후 전사에서 화자와 단어를 맞출 때 쓸 만하다.
- pyannote 모델은 처음 받을 때 Hugging Face에서 약관에 동의하고 계정 정보를 공유해야 한다. 받은 뒤에는 오프라인으로 돈다. 이 프로젝트는 모델 파일을 관리자 화면에서 커밋 고정·sha256으로 받는데, 약관 동의가 필요한 모델은 토큰을 서버 환경변수로 넣어야 한다.

## 4. 유료·클라우드

| 서비스 | 화자분리 | 한국어 | 데이터 | 가격 |
| --- | --- | --- | --- | --- |
| pyannoteAI precision-2 | 파일 단위. 공개 표에서 가장 낮다(AMI SDM 15.6, DIHARD3 14.7) | 확인 필요 | 외부(pyannoteAI 서버, EU). 온프레미스는 Enterprise 계약 | 시간당 €0.112(Developer)·€0.096(Starter), 월 €19·€99 요금제 안에서 차감 |
| pyannoteAI Live-1 | 스트리밍, 지연 300ms | 확인 필요 | 외부 | 시간당 €0.198(Developer)·€0.170(Starter) |
| Google Speech-to-Text v2 Chirp 3 | GA. 파일 전사(BatchRecognize)에서. 동기 Recognize는 문서가 엇갈려 확인 필요. **스트리밍은 안 됨** | 화자분리 언어 목록에 한국어 있음 | 사내 GCP, 리전 us·eu | [stt.md](stt.md) |
| Azure AI Speech | 실시간 화자분리 GA(2024-05, `ConversationTranscriber`, Guest-1·Guest-2 …). 배치는 모노, 최대 35명 | 한국어 STT는 지원. 한국어 실시간 화자분리는 확인 필요 | 외부(Azure). 온프레미스 컨테이너 v5.1.0부터 실시간 화자분리(Redis 필요) | [stt.md](stt.md) |
| AWS Transcribe | 배치·스트리밍 모두, 최대 30명(스트리밍 한도는 확인 필요) | 한국어 배치·스트리밍 지원 | 외부(AWS) | [stt.md](stt.md) |
| NAVER CLOVA Speech | 파일(장문) 인식에서만. **실시간 스트리밍은 안 됨** | 기본 언어 | 외부(네이버 클라우드, 한국) | [stt.md](stt.md) |

클라우드는 녹음 원본을 그 서비스로 보낸다. 사내 GCP 밖이면 "음성 원본은 승인된 원본 영역 밖으로 보내지 않는다" 원칙에 걸려 보안 승인이 먼저다.

## 5. 목소리로 사람을 알아보기 (쓰지 않음)

- 면접관이나 지원자의 목소리를 미리 등록해 화자를 이름으로 잇는 방식(pyannoteAI voiceprint, 음성 등록)은 쓰지 않는다.
- 개인정보 보호법 시행령 제18조 제3호는 "특정 개인을 알아볼 목적으로 일정한 기술적 수단을 통해 생성한" 신체적·행동적 특징 정보를 민감정보로 둔다. 법 제23조에 따라 별도 동의나 법적 근거가 있어야 처리한다.
- 개인정보의 안전성 확보조치 기준(개인정보보호위원회 고시)은 생체정보의 예로 음성을 들고, 특정 개인을 알아보려고 처리하는 것을 생체인식정보로 정의하며 암호화를 요구한다.
- 화자분리만 하고(이름 없이 나누기) 누가 누구인지는 사람이 지정하면 이 문제를 피한다. 현행 개인정보보호위원회 안내서에서 화자분리용 임시 특징 벡터를 어떻게 보는지는 확인 필요다(2021년 생체정보 보호 가이드라인은 "과거 안내서"로 바뀌었다).

## 6. 이 프로젝트 기준 권장

| 면접 방식 | 권장 | 이유 |
| --- | --- | --- |
| 비대면 | 참가자 트랙으로 나눈다. 모델 없음 | 정확하고 실시간. 남는 위험은 에코라 브라우저 AEC와 이어폰으로 막는다 |
| 대면, 지원자 1명 (PoC 기본) | 지원자 마이크를 따로 두고, 가능하면 면접관 쪽 마이크 하나를 더 둬서 소리 크기 비교로 지원자 구간을 고른다. 모델 없음 | 우리가 맞혀야 할 것은 "지원자인가"뿐이다. 실시간에 계산이 거의 들지 않는다 |
| 대면, 방 마이크 하나 (예외) | 실시간은 화자 없이 전사만, 사후 전사에서 화자분리 + 면접관이 "화자2 = 지원자"를 지정·수정 | 공개 모델도 원거리 마이크 DER이 11~23%다. 실시간은 더 나쁘다 |

방 마이크 하나일 때 모델 후보:

1. **pyannote community-1 (로컬, CPU)**: 상업 사용 가능, 회사 밖으로 나가는 것이 없다. 이 노트북 CPU에서 1시간 녹음에 얼마나 걸리는지 먼저 잰다. `config/providers.yaml`에 대안으로 적혀 있다.
2. **Chirp 3 배치 화자분리 (사내 GCP)**: STT 사후를 Chirp로 하면 같은 호출에서 받는다. 지금 화자분리 역할의 기본값(`google_stt_v2`, 구현 전)이다.
3. **Nemotron-3-Diarization 또는 Streaming Sortformer (GPU 서버가 생기면)**: 실시간 화자분리가 꼭 필요할 때만. 한국어 성능을 먼저 잰다.

쓰지 않는 것: 비상업 가중치(Sortformer v1, DiariZen), 목소리 등록, 회사 밖 화자분리 API(승인 전).

재는 법: 실제 대면 면접 녹음(동의 받은 것)에 사람이 지원자 구간을 표시하고, DER와 함께 우리에게 중요한 두 값을 본다. 지원자 말 중 지원자로 붙은 비율, 면접관 말이 지원자로 붙은 비율(채점 오염).

## 출처

확인 날짜 2026-10-27.

- [pyannote-audio (GitHub, DER 표·속도)](https://github.com/pyannote/pyannote-audio)
- [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannoteAI 가격](https://www.pyannote.ai/pricing), [precision-2 가격 (블로그)](https://www.pyannote.ai/blog/build-vs.-buy-the-real-cost-of-self-hosting-diarization)
- [diart](https://github.com/juanmc2005/diart)
- [NVIDIA NeMo](https://github.com/NVIDIA-NeMo/NeMo)
- [diar_sortformer_4spk-v1](https://huggingface.co/nvidia/diar_sortformer_4spk-v1), [diar_streaming_sortformer_4spk-v2](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2), [v2.1](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1)
- [Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization)
- [diar_msdd_telephonic (NGC)](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/diar_msdd_telephonic)
- [WhisperX](https://github.com/m-bain/whisperX), [한국어 정렬 모델 목록](https://raw.githubusercontent.com/m-bain/whisperX/main/whisperx/alignment.py), [kresnik/wav2vec2-large-xlsr-korean](https://huggingface.co/kresnik/wav2vec2-large-xlsr-korean)
- [DiariZen](https://github.com/BUTSpeechFIT/DiariZen), [diarizen-wavlm-large-s80-md-v2](https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md-v2)
- [3D-Speaker](https://github.com/modelscope/3D-Speaker)
- [Picovoice Falcon](https://github.com/Picovoice/falcon)
- [Chirp 3 (Google Cloud)](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)
- [Azure 실시간 화자분리 GA (2024-05)](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/announcing-general-availability-of-real-time-diarization/4147556), [Azure 화자분리 시작하기](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-stt-diarization), [Azure STT 컨테이너](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-container-stt), [Azure 배치 전사](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-transcription-create)
- [AWS Transcribe 화자분리](https://docs.aws.amazon.com/transcribe/latest/dg/diarization.html), [기능 표](https://docs.aws.amazon.com/transcribe/latest/dg/feature-matrix.html), [지원 언어](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html)
- [CLOVA Speech 문제 해결 (스트리밍 화자분리 불가)](https://guide.ncloud-docs.com/docs/clovaspeech-troubleshoot-common), [CLOVA Speech 장문 인식](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence)
- [한국어 유아 대화 화자분리 (arXiv 2606.10213)](https://arxiv.org/abs/2606.10213)
- [개인정보 보호법 제23조](https://www.law.go.kr/법령/개인정보보호법/제23조), [시행령 제18조](https://www.law.go.kr/법령/개인정보보호법시행령/제18조), [개인정보의 안전성 확보조치 기준](https://www.law.go.kr/행정규칙/개인정보의안전성확보조치기준)
- [pyannote.metrics (DER 정의, collar)](https://pyannote.github.io/pyannote-metrics/reference.html)

### 확인 필요

- pyannote 3.1·community-1의 CPU 속도, 약관 동의 때 모으는 계정 정보 항목
- pyannoteAI의 데이터 보관 기간, 온프레미스 가격·조건, 한국어 성능
- diart의 DER
- NeMo 모델의 CPU 실용성과 한국어 성능, MSDD telephonic의 NGC 약관 밖 라이선스, Streaming Sortformer v2.1의 NVIDIA Open Model License 조건
- 3D-Speaker 가중치 라이선스와 DER 측정 조건
- Picovoice Falcon 가격·언어·DER
- Chirp 3 동기 Recognize의 화자분리 지원, 최소·최대 화자 수
- Azure 한국어 실시간 화자분리 지원
- AWS 스트리밍의 30명 한도
- CLOVA 화자 수 설정과 한도
- 한국어 면접(대화) 화자분리 공개 평가
- 현행 개인정보보호위원회 안내서가 음성·화자 인식·특징 정보를 어떻게 보는지
