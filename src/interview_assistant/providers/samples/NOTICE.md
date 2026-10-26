# Sample audio

`ko-fleurs-1894.wav`: one utterance from the Korean (ko_kr) test split of FLEURS, row id 1894,
11.5 s, read speech. Converted from 32-bit float to 16 kHz mono 16-bit PCM and peak-normalized;
otherwise unchanged.

Transcript: 커리는 약용 식물과 향신료를 기본으로 하여 고기나 채소를 곁들이는 요리입니다.

FLEURS: A. Conneau, M. Ma, S. Khanuja, Y. Zhang, V. Axelrod, S. Dalmia, J. Riesa, C. Rivera,
A. Bapna, "FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech",
2022 (https://arxiv.org/abs/2205.12446). Dataset by Google, https://huggingface.co/datasets/google/fleurs,
licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

Used for the STT connection test on the admin screen (admin > 모델 설정) and in tests.

# Sample documents

`documents/`: fictional resumes from the leak-check fixtures (tests/fixtures/resumes, made by
scripts/make_resume_fixtures.py; every person, number and address is invented, phone numbers in
the unassigned 010-0xxx/1xxx ranges, e-mail at RFC 2606 example domains). Used for the 서류 읽기
test on the admin screen; `samples.json` holds each one's identity (for de-identifying the
preview) and the text drawn into its pictures (for the OCR error rate).

- `reading-sample.pdf` (R27): a typed page with a certificate picture and an ID photo, then a scanned page
- `ocr-sample.png` (R25): a resume captured as a picture
- `pdf-sample.pdf` (R26): a PDF whose Korean font has a broken ToUnicode map (garbled text layer)
- `hwp-sample.hwpx` (R21): an HWPX with headers, footnotes, hidden comments, white text, a certificate
- `legacy-sample.doc` (R29): a Word 97-2003 file saved by LibreOffice
