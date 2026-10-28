# 참고 자료

2026-10-27 · 모델·라이브러리를 고르거나 음성 입력을 붙일 때 다시 찾게 되는 비교와 배경 지식을 모은 폴더다. 여기 있는 것은 "무엇이 있고 각각 어떤가"이고, "우리는 무엇으로 정했나"와 "이 PC에서 재 보니 얼마였나"는 기존 문서에 있다.

| 문서 | 답하는 질문 |
| --- | --- |
| [libraries.md](libraries.md) | 이 프로젝트가 쓰거나 검토한 라이브러리·모델·클라우드 서비스는 무엇이고, 라이선스·비용·데이터가 나가는지·상태는? |
| [llm.md](llm.md) | 사내 서버에 올릴 오픈 웨이트 LLM은 무엇이 있고, 라이선스·출처 국가·GPU 메모리·한국어 성능·첫 토큰에서 작업별로 무엇이 맞나? (2026-10-28) |
| [stt.md](stt.md) | 한국어 면접 전사에 쓸 수 있는 STT는 무엇이고, 정확도·지연·데이터 위치·가격에서 무엇을 얻고 잃나? |
| [diarization.md](diarization.md) | 누가 말했는지 어떻게 나누나? 모델 없이 되는 방법과 모델·클라우드별 장단점은? |
| [audio-quality.md](audio-quality.md) | 전사 품질은 마이크부터 무엇이 좌우하고, 답변 끝 판단은 어떻게 하며, 품질을 어떻게 재나? |
| [glossary.md](glossary.md) | 이 프로젝트의 용어는 무슨 뜻이고 코드·문서 어디에 있나? |

## 기존 문서와의 관계

| 종류 | 문서 | 여기와의 관계 |
| --- | --- | --- |
| 결정 메모 | [model-selection.md](../model-selection.md) | 역할별 기준, 실시간 STT 선택지, 면접 방식별 오디오, BGE-M3 결정. 여기는 그 결정의 배경 비교다. 결정이 바뀌면 그쪽을 고친다 |
| 측정값 | [whisper-benchmark.md](../whisper-benchmark.md), [ocr-benchmark.md](../ocr-benchmark.md), [embedding-benchmark.md](../embedding-benchmark.md) | 이 노트북에서 잰 숫자의 원본. 여기서는 인용만 하고 출처를 적는다 |
| 사용법 | [ai-models.md](../ai-models.md), [document-reading.md](../document-reading.md), [question-bank.md](../question-bank.md) | 관리자 화면, 설치, 규칙. 여기서는 다시 쓰지 않고 링크한다 |
| 보안 | [deidentification.md](../deidentification.md), [site-intake-spec.md](../site-intake-spec.md) | 비식별화와 연동 규칙. 외부 서비스 비교에서 "무엇이 회사 밖으로 나가나"는 이 원칙에 비추어 적었다 |

## 읽을 때 주의

- 가격·라이선스·지원 언어는 바뀐다. 각 문서 끝에 출처와 확인 날짜가 있다. 계약이나 결정 전에는 원문을 다시 확인하고 날짜를 고친다.
- 공식 문서에서 확인하지 못한 것은 "확인 필요"로 적었다. 추측으로 채우지 않는다.
- 숫자는 두 종류다. 이 저장소에서 잰 값(측정 문서 링크)과 공개 벤치마크(출처 링크). 공개 벤치마크는 영어·중국어 데이터가 대부분이라 한국어 면접에서는 달라질 수 있다. 결정은 실제 면접 녹음(동의 받은 것)으로 다시 재서 한다.
