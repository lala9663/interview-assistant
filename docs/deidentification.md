# 비식별화

업무정의서 9장. LLM에는 `Deidentifier`를 거친 텍스트만 보낸다. 같은 지원자 안에서 같은 값은 세션·문서를 가로질러 항상 같은 토큰(`[지원자]`, `[학교-1]`, `[회사-2]` …)이 된다. 원래 값은 `deid_mappings`에 암호화해 두며, 되돌리는 것은 `deid/reidentify.py`만 한다.

## 코드

```
src/interview_assistant/deid/
  deidentifier.py     # 원문 -> 토큰 치환 텍스트. LLM으로 가는 유일한 통로
  service.py          # 앱용: 설정·사전·탐지기를 한 번 만들고 DB 세션마다 Deidentifier를 준다
  detectors/          # 교체 가능한 탐지기: 본인 정보, 정규식, 사전, 형태 패턴, 호칭 붙은 이름, NER 자리, OCR 오독(ocr.py)
  store.py            # 토큰 발급과 역매핑 저장 (원래 값은 암호화)
  reidentify.py       # 재식별. 역매핑을 복호화하는 유일한 곳, 호출마다 감사 로그
  documents.py        # 추출 문서 전체(파일명·속성 포함)를 블록 단위로 비식별화. OCR 블록에는 너그러운 탐지기를 더한다. 보류된 쪽이 있으면 거부
  leaks.py            # 누출 검수 로직 (텍스트 샘플, 파일 샘플)
  review.py           # 사람이 보는 검토 리포트 (HTML 1개)
src/interview_assistant/documents/   # 서류 읽기 (document-reading.md)
  base.py             # DocumentExtractor 인터페이스, 형식 판별, extract_document
  reading.py          # DocumentReader: 쪽마다 텍스트 층 또는 OCR, 읽기 기록
  pdf.py, word.py, powerpoint.py, webpage.py, hwp.py, hwpx.py, image.py, legacy.py
  normalize.py        # NFC, 제로폭 문자 제거, 전각 숫자 변환 (모든 추출 결과에 적용)
```

```python
config = load_deid_config(Settings().deid_file)
store = SqlTokenStore(session, FieldCipher.from_settings(), config.token_formats())
result = build_deidentifier(config, store).deidentify(text, candidate_id=cid, known=identity)
```

## 설정

- 토큰 형식, 사전 파일, 켤 탐지기, 치환 예외는 `config/deid.yaml`에서 바꾼다. 토큰 형식은 아직 초안이다.
- 학교·회사 사전은 `config/deid/*.txt` (한 줄에 `정식명 | 별칭 | ...`). 사내 목록은 파일을 추가하고 `deid.yaml`에 나열한다.
- 한국어 NER은 `deid/detectors/ner.py`의 `EntityRecognizer`를 구현해 붙인다. 지금은 모델 없이 규칙 기반이다.

## 글자 사이 공백 (자간)

"0 1 0 - 1 2 3 4 - 5 6 7 8", "john @ example . com", "누 리 대 학 교"처럼 띄어 쓴 값도 지원서에 없는 값까지 규칙으로 잡는다.

- 전화·이메일·주민번호 정규식과 학교·회사 형태 패턴은 원문과 함께 공백을 뺀 사본(`deid/text.py`의 `without_letter_spacing`, 사본→원문 위치 대응표)에도 돌리고, 찾은 구간을 원문 위치로 되돌려 띄어 쓴 원문 전체를 치환한다.
- 사본에서 빼는 공백은 한 글자끼리 사이(그중 가장 좁은 간격)와 @ . - _ 앞뒤뿐이라 "있는 대학교" 같은 일반 단어는 붙지 않는다. 전화는 010·지역번호 접두와 자릿수, 이메일은 @와 도메인, 주민번호는 유효한 날짜가 그대로 필요하다.
- 이름처럼 단어 경계가 필요한 탐지는 원문에서만 하며, 지원서 이름은 글자 사이 공백 여러 칸("권  하  린")까지 허용한다.
- 남은 한계: 지원서에 없는 띄어 쓴 제3자 이름·영문 이름·생년월일·주소, 사전에만 있고 형태로는 안 보이는 기관명("카 카 오")은 못 잡는다. 글자마다 띄어 쓴 문장은 학교·회사 이름으로 과잉 치환될 수 있다.

## 누출 검수 (텍스트)

합성 샘플 20건, 네트워크 없이:

```bash
uv run python scripts/check_leaks.py
```

실제 샘플로 검수할 때는 같은 형식의 YAML을 만들어 `--samples`로 넘긴다. 리포트는 값을 가려서 출력한다(`--show-values`로 해제). 정답 목록에 없어도 전화·이메일·주민번호 형태가 남으면 실패이며, 이 검사는 공백을 전부 뺀 사본도 보므로 띄어 쓴 값이 남아도 드러난다.

## 서류 파일

LLM으로 가는 서류 텍스트는 읽기(`DocumentReader.read`, 앱은 관리자 설정으로 만든 것) → `deidentify_document`만 거친다. 그림은 OCR로 텍스트만 꺼내거나(설정) 세고 버리며, 증명사진은 읽지 않고 버린다. 원본 파일이나 그림을 모델로 보내는 경로는 없다.

```python
document = runtime.models.active.reader.read(upload_bytes, upload_filename)   # 형식·쪽별 방법은 document-reading.md
# 설정 없이: extract_document(upload_bytes, upload_filename)  (OCR 없음, 스캔한 쪽은 보류)
result = deidentify_document(deid, document, candidate_id=cid, known=identity)
prompt_text = result.text   # 파일명·문서 속성·본문·표·머리글·바닥글·노트·링크·숨은 텍스트, 토큰 치환본
```

- 추출 결과는 블록 단위(`documents/types.py`의 `BlockKind`)다. 흰 글씨, 0.5pt 글자, 슬라이드 밖 도형, `display:none`처럼 보이지 않는 텍스트는 `hidden` 블록으로 따로 두고, 선별 프롬프트에서는 뺀다.
- PDF의 자간 넓힌 줄은 글자 좌표로 되돌린다(`documents/pdf.py`의 `close_letter_spacing`). 공백 글자 없이 고른 간격으로 이어진 세 글자 이상(같은 줄이면 두 글자 단어도)은 붙이고, 공백 글자나 더 넓은 간격은 단어 사이로 남긴다: "권 하 린 · 이 력 서" → "권하린 · 이력서". 보통 텍스트와 실제 공백으로 띄운 글자("이 력 서" 제목)는 바뀌지 않는다.
- 텍스트 층이 없거나 깨진 쪽은 읽기 방식에 따라 OCR로 읽는다([document-reading.md](document-reading.md)). 깨진 텍스트 층은 숨은 텍스트까지 버린다(되돌리면 이름이 나오는 바이트라서). 읽지 못한 쪽이 하나라도 있으면 `needs_ocr`이고, `deidentify_document`가 `OcrRequired`로 거부해 문서 전체를 보류한다.
- OCR 블록(`TextBlock.ocr`)에는 OCR 오독용 탐지기(`deid/detectors/ocr.py`)를 더 돌린다: 지원서 값과 자모 거리 1~2인 이름·학교·회사(단어 경계 없이), 띄어 쓰거나 호칭이 잘린 이름, 숫자 하나 틀린 전화번호, 이메일·영문 이름의 글자 뼈대. OCR 줄은 그 전에 비슷한 글자를 숫자로 고친다(`documents/ocrfix.py`). 일반 텍스트에는 쓰지 않는다(과잉 치환 방지).
- 형식: PDF, DOCX, PPTX, HTML, HWP 5.0, HWPX, 구형 .doc/.ppt(LibreOffice 변환), JPG/PNG. 암호 문서는 `EncryptedDocument`, 변환기가 없으면 `ConverterMissing`, 나머지는 `UnsupportedFormat`.
- 추출기 교체: `extract_document(..., extractors={"pdf": MyPdfExtractor()})` 또는 `DocumentReader(extractors=...)`. 구현은 `DocumentExtractor`를 따른다.
- 라이브러리: pdfplumber(MIT, pdfminer.six MIT, pypdfium2 Apache-2.0/BSD-3), python-docx·python-pptx(MIT), beautifulsoup4(MIT), lxml(BSD), syhwp(MIT), olefile(BSD), Pillow(MIT-CMU), PaddleOCR·PaddlePaddle(Apache-2.0), Tesseract(Apache-2.0), LibreOffice(MPL-2.0, 별도 프로그램으로 실행). PyMuPDF·pyhwp(AGPL)는 쓰지 않는다.

### 파일 단위 누출 검수

가상 이력서 31건: 읽기 → 비식별화 → 정답 값 검사, 파일명·속성 포함, 네트워크 없음.

```bash
uv run python scripts/check_leaks.py --documents                    # OCR 없이: 스캔·그림이 있는 8건은 보류로 분류
uv run python scripts/check_leaks.py --documents --ocr paddleocr    # OCR 포함 (모델 파일 필요)
```

OCR을 켜면 정답 값이 그대로 남은 누출 외에 OCR이 잘못 읽은 채 남은 "근접 누출"도 센다: 자모 근사 일치(비슷한 모양 글자는 같은 글자로 보고, 토큰은 가린 뒤), 전화·주민번호 숫자 편집 거리 1. OCR 글자 오류율(정답 그림 텍스트 대비)과, 그림에 있던 값을 OCR이 아예 못 읽은 경우(`ocr_missed`, 누출은 아니지만 선별 품질 문제)도 보고한다. 암호 문서는 거부되어야 통과다.

결과(2026-10-26): OCR 없이 22건 누출 0·보류 8·거부 1. PaddleOCR로 30건 누출 0·근접 누출 0(정답 값 389개)·거부 1, 글자 오류율 평균 0.5%. Tesseract best·fast도 누출 0.

### 검토 리포트

샘플별 원본 추출 텍스트와 비식별본을 나란히 보고, 토큰 강조, 속성·버린 이미지 수, 쪽마다 읽은 방법·도구·신뢰도·시간과 그림마다 판단(OCR·증명사진 버림), 근접 누출, 글자 오류율, OK/누출을 체크한다. `--ocr`을 같이 주면 OCR한 결과로 만든다.

```bash
uv run python scripts/check_leaks.py --documents --report
```

리포트는 `reports/deid-review.html`에 생기고 브라우저로 연다. 원문이 그대로 들어 있으므로 원본 영역 문서로 다룬다: `reports/`는 git에서 제외되어 있고, 공유·첨부하지 않는다. 체크 결과는 그 브라우저에만 저장되며 "결과 복사"(TSV)나 "결과 저장"(JSON)으로 꺼낸다. 실제 서류로 검수할 때는 같은 형식의 manifest를 만들어 `--documents path/to/manifest.yaml`로 넘긴다.

### 가상 이력서 다시 만들기

dev 의존성 reportlab, pillow가 필요하다. 구형 .doc·.ppt는 LibreOffice로 만들므로 `--legacy`를 줄 때만 다시 만든다(없으면 커밋된 파일을 둔다). HWP 5.0·HWPX는 `scripts/hwp_writers.py`가 규격대로 쓴다. 한글 PDF와 스캔 이미지에 쓸 TrueType 폰트는 시스템에서 읽고 커밋하지 않는다. 기본으로 맑은 고딕·나눔고딕 경로를 찾고, 다른 폰트는 `--font` 또는 `IA_FIXTURE_FONT`로 준다.

```bash
uv run python scripts/make_resume_fixtures.py --font C:/Windows/Fonts/malgun.ttf
```

같은 폰트면 결과 파일이 바이트 단위로 같고, `manifest.yaml`(정답 목록)은 파일을 그리면서 기록한 값으로 쓴다.
