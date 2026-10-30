# 로컬 OCR 측정 (PaddleOCR, Tesseract, CPU)

> 다루는 것: 이 노트북(GPU 없음)에서 잰 PaddleOCR·Tesseract의 쪽당 속도·메모리·한국어 정확도.
>
> 상태: 구현됨(측정 2026-10-26) · 확인: 2026-10-30

`scripts/bench_ocr.py`로 측정했다. 관리자 > 모델 설정의 OCR provider(`providers/ocr/`)를 서류 읽기 경로(`DocumentReader`, 자동 방식) 그대로 돌렸다. 쪽 그림 만들기, 증명사진 판정, 비슷한 글자 고치기까지 포함한 시간이다. 규칙은 [document-reading.md](document-reading.md).

## 조건

| 항목 | 값 |
| --- | --- |
| PC | 노트북, Intel Core i7-1360P (4P + 8E 코어, 16 스레드), RAM 16GB, NVIDIA GPU 없음. 전원 연결 |
| PaddleOCR | paddleocr 3.7.0, paddlepaddle 3.2.2(CPU, oneDNN 켬), PP-OCRv5_mobile_det + korean_PP-OCRv5_mobile_rec, 줄·쪽 방향 보정 끔, CPU 스레드 12 |
| Tesseract | 5.4.0 (UB-Mannheim Windows 빌드), kor+eng, tessdata best·fast, `--psm 3` |
| 서류 | OCR 정답이 있는 가상 이력서 10건, OCR 14번(쪽 10, 문서 속 그림 4): 스캔 PDF 3건(R18–R20), HWPX 속 자격증 그림(R21), 기울고 흐린 휴대폰 사진 JPG(R24), 화면 캡처 PNG(R25), 글자 깨진 PDF 2쪽(R26), 텍스트+스캔 혼합 PDF와 그림(R27), DOCX 속 자격증 그림(R28), 캡처 슬라이드 PPTX(R30). PDF는 200dpi |
| 정답 | 그림에 그린 텍스트. 글자 오류율(CER) = 공백·문장부호를 뺀 글자 편집 거리 / 정답 글자 수 |
| 메모리 | 이 프로세스와 자식 프로세스(Tesseract)의 최대 상주 메모리, 50ms마다 |

이 PC는 다른 작업(다른 세션의 서버·개발 서버·브라우저, CPU 30~45%)과 같이 쓰였다. PaddleOCR을 세 번 돌렸는데, 다른 작업과 겹친 한 번은 쪽당 중앙값 11초로 다른 두 번(4~5초)의 2~3배였다. 정확도는 세 번 모두 같았다(결정적이다). 속도는 범위로 읽는다. 다른 작업이 없을 때 엔진만 따로 잰 값은 쪽당 1.7~3.5초였다.

## 결과

| 엔진 | 쪽·그림당 시간 (중앙값 / 범위) | 최대 메모리 | 엔진 준비 · 첫 읽기 | 글자 오류율 (평균 / 최대) | 최저 신뢰도 |
| --- | ---: | ---: | ---: | ---: | ---: |
| PaddleOCR mobile | 3.9~5.0초 / 1.8~7.4초 (겹친 작업이 있으면 11초 / 3~18초) | 1.3~1.6GB (프로세스 전체) | 5.5초 · 5~6초 | 0.5% / 2.3% | 92% |
| PaddleOCR server 검출 | 29~37초 (엔진만, 이전 측정) | 약 2.9GB | | | |
| Tesseract best | 2.2초 / 0.8~7.5초 | 141MB + 프로그램 86MB | 0.1초 · 5.5초 | 28.8% / 93.7% | 50% |
| Tesseract fast | 1.2초 / 0.5~2.9초 | 131MB + 프로그램 65MB | 0.1초 · 2.2초 | 31.3% / 100% | 52% |

샘플별 (PaddleOCR mobile은 조용할 때 두 번 중 두 번째, 시간은 쪽·그림 순서):

| 샘플 | 내용 | PaddleOCR 시간 | PaddleOCR CER | Tesseract best CER | Tesseract fast CER |
| --- | --- | --- | ---: | ---: | ---: |
| R18 | 스캔 PDF 1쪽 | 5.3 | 0.6% | 6.3% | 7.4% |
| R19 | 스캔 PDF 2쪽 | 3.8, 4.5 | 0.5% | 3.8% | 6.0% |
| R20 | 스캔 PDF 1쪽 | 3.8 | 2.3% | 2.3% | 8.5% |
| R21 | HWPX 속 자격증 그림 | 1.8 | 0.0% | 60.2% | 60.2% |
| R24 | 기울고 흐린 휴대폰 사진 | 5.9 | 0.9% | 4.9% | 6.7% |
| R25 | 화면 캡처 PNG | 5.3 | 0.3% | 28.2% | 27.9% |
| R26 | 글자 깨진 PDF 2쪽 | 6.3, 6.0 | 0.2% | 93.7% | 100% |
| R27 | 혼합 PDF: 스캔 1쪽 + 그림 | 7.1, 2.3 | 0.0% | 18.3% | 20.9% |
| R28 | DOCX 속 자격증 그림 | 2.7 | 0.0% | 53.4% | 53.4% |
| R30 | 캡처 슬라이드 + 그림 | 5.0, 5.0 | 0.0% | 16.8% | 21.2% |

## 읽는 법

- **정확도는 PaddleOCR이 압도적이다.** 한국어 서류 10건 글자 오류율 평균 0.5%, 최대 2.3%(R20 스캔, 작은 글씨). 기울고 흐린 휴대폰 사진도 0.9%. 비식별화 검사에서 누출 0, 근접 누출 0.
- **Tesseract는 깨끗한 스캔(R18–R20, 2~9%)은 쓸 만하지만 색 배경·굵은 글꼴·캡처에서 무너진다.** 자격증 그림 53~60%, 깨진 PDF를 다시 읽은 R26은 94~100%(2쪽 신뢰도 50%). 누출은 OCR 오독 대책 뒤 0이었지만, 읽은 내용이 틀려 선별 품질이 떨어진다. 빠르고 가벼운 비교용으로만 둔다.
- **속도**: PaddleOCR mobile은 A4 한 쪽에 몇 초라 지원서 한 건(1~3쪽)이 10~20초 늘어난다. 사이트 연동 큐(워커 4)라면 받는 대로 처리할 만하다. 다만 이 PC처럼 다른 작업이 CPU를 쓰면 2~3배 느려진다. 서버는 OCR 전용 코어를 따로 잡거나 동시 OCR 수를 제한할 것.
- **server 검출은 이 CPU로 부적합하다.** 쪽당 30초 이상, 메모리 2.9GB. GPU 서버가 생기면 다시 잴 것.
- **메모리**: 위 표의 PaddleOCR 값은 엔진이 측정 프로세스 안에서 돌 때 잰 것이다(파이썬·PDF 라이브러리 포함 1.3~1.6GB). 지금 PaddleOCR은 작업 프로세스에서 돈다(faster-whisper와 DLL이 충돌해서, [document-reading.md](document-reading.md)). 서버 프로세스는 가벼워지고(스캔 1쪽을 두 번 읽은 뒤 최대 91MB) 작업 프로세스가 모델 메모리를 진다(최대 1.8GB, 쉴 때 0.55GB). Whisper와 같이 쓰면 두 프로세스를 합쳐서 계산한다(Whisper medium 1.8GB). Tesseract는 쪽마다 프로그램을 띄워 100MB 아래로 끝난다.
- **엔진 준비**: PaddleOCR은 적용할 때 미리 올린다(워밍업 약 5초). 첫 읽기는 그 뒤 한 번 더 느리다.

## 다시 재기

모델 파일은 관리자 화면에서 받거나 `IA_WEIGHTS_DIR`에 둔다. 엔진마다 프로세스를 따로 띄운다.

```bash
uv run python scripts/bench_ocr.py --engine paddleocr --model ppocrv5-mobile
uv run python scripts/bench_ocr.py --engine tesseract --model best
uv run python scripts/bench_ocr.py --engine tesseract --model fast
```

실제 서류로 잴 때는 같은 형식의 manifest(`ocr_truth`에 그림 속 정답 텍스트)를 만들어 `--manifest`로 넘긴다.
