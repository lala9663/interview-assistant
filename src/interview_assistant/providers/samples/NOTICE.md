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

`answer-pauses.wav`: a made-up answer with thinking pauses, 16.6 s, built by joining two utterances
of the same FLEURS ko_kr test split, rows 1709 and 1910 (16 kHz mono 16-bit): 0.6 s of room tone,
row 1709 with 1.5 s of room tone put into its pause after "이라크 정책에", 1.9 s of room tone, row
1910, 0.6 s of room tone. The room tone is the quietest audio of row 1709, repeated. Otherwise
unchanged. Used as the diagnostic microphone input of the live interview (docs/audio-input.md).

Transcript: 보고서는 행정부의 현재 이라크 정책에 대해 거의 모든 측면에서 매우 비판적이며 즉각적인 방향
변경을 촉구합니다. 파리 사람들은 자기중심적이고, 무례하고, 오만하다는 평판이 있습니다.

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
