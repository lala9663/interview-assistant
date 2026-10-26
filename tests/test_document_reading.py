"""Reading documents (documents/reading.py): text layer or OCR per page, HWP/HWPX, pictures as
files and inside documents, garbled text layers, legacy Office files, and the reading record.

The OCR here is the fake engine (reads nothing, or the lines a test gives it), so these run
without models and without network. Real engines: test_ocr_engines.py (skipped without models).
"""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image, ImageDraw

from interview_assistant.deid.documents import OcrRequired, deidentify_document
from interview_assistant.deid.leaks import load_document_samples, real_path
from interview_assistant.documents import BlockKind, ExtractionError
from interview_assistant.documents.base import ConverterMissing, EncryptedDocument, detect_format
from interview_assistant.documents.images import check_picture, text_metadata
from interview_assistant.documents.legacy import LibreOfficeConverter
from interview_assistant.documents.ocrfix import correct
from interview_assistant.documents.reading import DocumentReader, ReadingPolicy
from interview_assistant.documents.types import ReadMethod
from interview_assistant.providers import programs
from interview_assistant.providers.base import OcrLine, OcrResult
from interview_assistant.providers.fake import FakeOCR

from .conftest import ROOT

MANIFEST = ROOT / "tests" / "fixtures" / "resumes" / "manifest.yaml"
HAS_LIBREOFFICE = programs.LIBREOFFICE.find() is not None


@pytest.fixture(scope="module")
def samples():
    return {s.id: s for s in load_document_samples(MANIFEST)}


def read(sample, *, ocr=None, converter=None, **policy):
    reader = DocumentReader(policy=ReadingPolicy(**policy), ocr=ocr or FakeOCR(), converter=converter)
    return reader.read(sample.path.read_bytes(), sample.upload_name)


def text(doc, *kinds: BlockKind) -> str:
    return "\n".join(b.text for b in doc.blocks if not kinds or b.kind in kinds)


# --- formats ---------------------------------------------------------------------------------


def test_every_new_format_is_detected_from_its_content(samples):
    expected = {"R21": "hwpx", "R22": "hwp", "R23": "hwp", "R24": "image", "R25": "image", "R29": "doc", "R31": "ppt"}
    for i, fmt in expected.items():
        assert detect_format(samples[i].path.read_bytes(), "renamed.bin") == fmt, i


def test_hwpx_blocks_properties_hidden_text_and_links(samples):
    doc = read(samples["R21"], embedded_images=False)
    assert doc.format == "hwpx" and not doc.needs_ocr
    assert doc.metadata["작성자"] == "도하윤" and doc.metadata["마지막 수정자"] == "Hayun Do"
    assert "도하윤" in doc.metadata["변경 추적 작성자"]
    assert "도하윤" in text(doc, BlockKind.header) and "010-0517-2846" in text(doc, BlockKind.header)
    assert "도하윤 이력서" in text(doc, BlockKind.footer)
    assert "010-0782-3315" in text(doc, BlockKind.comment)  # footnote
    hidden = text(doc, BlockKind.hidden)
    assert "hayun.do@example.com" in hidden  # 숨은 설명
    assert "01005172846" in hidden  # white run
    assert "010-0517-2846" in hidden  # preview text (PrvText)
    assert "01005172846" not in text(doc, BlockKind.body)
    assert "mailto:hayun.do@example.com" in text(doc, BlockKind.link) and "hayun-do" in text(doc, BlockKind.link)
    assert "010.0517.2846" in text(doc, BlockKind.body)  # text box
    assert [t.split(" | ")[0] for t in text(doc, BlockKind.table).splitlines()][:2] == ["인적사항", "성명"]
    assert {(i.label, i.decision) for i in doc.images} == {("그림 1", "photo"), ("그림 2", "skipped")}


def test_hwpx_certificate_picture_is_read_and_its_name_de_identified(samples, deid_config):
    sample = samples["R21"]
    lines = ["국가기술자격증", "성명: 도하윤", "생년월일: 1997.05.21"]
    doc = read(sample, ocr=FakeOCR(lines=lines, confidence=0.95))
    pictures = {i.label: i for i in doc.images}
    assert pictures["그림 1"].decision == "photo"  # the ID photo is never read
    assert pictures["그림 2"].decision == "ocr" and pictures["그림 2"].confidence == pytest.approx(0.95)
    block = next(b for b in doc.blocks if b.kind is BlockKind.image_text)
    assert block.ocr and block.label == "그림 2 (OCR)" and "도하윤" in block.text
    with real_path(deid_config) as (deid, enroll):
        cid, known = enroll("R21", sample.identity)
        result = deidentify_document(deid, doc, candidate_id=cid, known=known)
    assert "도하윤" not in result.text and "1997.05.21" not in result.text


def test_hwp5_controls_properties_and_preview(samples):
    doc = read(samples["R22"])
    assert doc.format == "hwp" and doc.reading.tools[0].startswith("syhwp 0.0.8")
    assert doc.metadata["작성자"] == "추서진" and doc.metadata["마지막 수정자"] == "Seojin Choo"
    assert "seojin.choo@example.org" in doc.metadata["키워드"]
    assert "010.1628.4093" in text(doc, BlockKind.header)
    assert "추서진 입사지원서" in text(doc, BlockKind.footer)
    assert "010-1904-6627" in text(doc, BlockKind.comment)  # footnote
    assert "seojin.choo@example.org" in text(doc, BlockKind.hidden)  # 숨은 설명
    assert "seojin.choo@example.org" not in text(doc, BlockKind.body)
    assert "010-1628-4093" in text(doc, BlockKind.hidden)  # preview text
    assert "mailto:seojin.choo@example.org" in text(doc, BlockKind.link)
    assert "이팝꽃로 31" in text(doc, BlockKind.body)  # text box
    assert [i.decision for i in doc.images] == ["photo"]


def test_password_protected_hwp_is_refused(samples):
    with pytest.raises(EncryptedDocument, match="암호"):
        read(samples["R23"])


# --- pictures as files -----------------------------------------------------------------------


def test_a_photographed_resume_is_one_ocr_page_with_its_exif_author(samples):
    sample = samples["R24"]
    doc = read(sample, ocr=FakeOCR(lines=["성명: 기서윤"], confidence=0.9))
    assert doc.format == "image" and [p.method for p in doc.pages] == [ReadMethod.ocr]
    page = doc.pages[0]
    assert page.reason == "그림 파일" and page.tool == "fake OCR" and page.confidence == pytest.approx(0.9)
    assert doc.metadata["작성자"] in ("기서윤", "Seoyun Ki")
    assert ("작성자", "기서윤") in text_metadata(sample.path.read_bytes())  # XPAuthor (UTF-16)
    assert ("작성자", "Seoyun Ki") in text_metadata(sample.path.read_bytes())  # Artist
    assert [b.label for b in doc.blocks if b.ocr] == ["그림 (OCR)"]


def test_pictures_are_held_with_the_text_only_setting_or_without_an_engine(samples):
    doc = read(samples["R25"], mode="text_only")
    assert doc.needs_ocr and doc.pages[0].method is ReadMethod.held and "텍스트만" in doc.pages[0].reason
    doc = DocumentReader(policy=ReadingPolicy(), ocr=None).read(samples["R25"].path.read_bytes(), "x.png")
    assert doc.needs_ocr and "OCR 엔진이 설정되지 않음" in doc.pages[0].reason
    with pytest.raises(OcrRequired):
        deidentify_document(None, doc, candidate_id="x")  # type: ignore[arg-type]


def test_png_text_chunks_are_properties(samples):
    assert ("기타 속성", "Author: 어하준") in text_metadata(samples["R25"].path.read_bytes())


# --- PDFs ------------------------------------------------------------------------------------


def test_a_garbled_text_layer_is_dropped_and_read_by_ocr(samples):
    doc = read(samples["R26"], ocr=FakeOCR(lines=["이 력 서", "성명 남주원"]))
    assert [p.method for p in doc.pages] == [ReadMethod.ocr, ReadMethod.ocr]
    assert all("깨짐" in p.reason and p.garbled > 0.5 for p in doc.pages)
    everything = doc.render()
    assert "ÀÌ" not in everything and "³²ÁÖ¿ø" not in everything  # no mojibake anywhere
    assert doc.metadata["작성자"] == "남주원"  # the properties are fine and kept
    assert any("텍스트 층이 깨져 버림" in w for w in doc.warnings)


def test_a_garbled_text_layer_is_held_not_sent_with_the_text_only_setting(samples):
    doc = read(samples["R26"], mode="text_only")
    assert doc.needs_ocr and all(p.method is ReadMethod.held for p in doc.pages)
    assert "ÀÌ" not in doc.render()


@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_every_sensitivity_finds_the_garbled_sample_and_passes_the_clean_ones(samples, sensitivity):
    assert all(p.method is ReadMethod.ocr for p in read(samples["R26"], sensitivity=sensitivity).pages)
    for i in ("R01", "R02", "R03", "R04", "R05", "R06"):
        assert all(p.method is ReadMethod.text for p in read(samples[i], sensitivity=sensitivity).pages), i


def test_mixed_pdf_reads_pictures_on_text_pages_and_ocrs_the_scanned_page(samples):
    doc = read(samples["R27"], ocr=FakeOCR(lines=["성명: 주예린"]))
    assert [p.method for p in doc.pages] == [ReadMethod.text, ReadMethod.ocr]
    assert doc.pages[0].tool.startswith("pdfplumber") and doc.pages[1].reason == "텍스트 층 없음"
    decisions = {i.label: i.decision for i in doc.images}
    assert decisions == {"1쪽 그림 1": "photo", "1쪽 그림 2": "ocr"}
    assert [b.label for b in doc.blocks if b.ocr] == ["1쪽 그림 2 (OCR)", "2쪽 (OCR)"]


def test_always_ocr_reads_every_page_but_keeps_what_only_the_file_holds(samples):
    doc = read(samples["R01"], mode="always_ocr")
    assert all(p.method is ReadMethod.ocr and p.reason == "항상 OCR 설정" for p in doc.pages)
    assert not doc.blocks_of(BlockKind.table)  # the text layer's running text is replaced
    assert doc.blocks_of(BlockKind.hidden) and doc.metadata["작성자"] == "권하린"
    assert "github.com/harin-kwon" in text(doc, BlockKind.link)


def test_text_pdfs_record_their_reader(samples):
    doc = read(samples["R03"])
    assert doc.reading.mode == "auto" and doc.reading.tools == ("pdfplumber 0.11.10",)
    assert all(p.method is ReadMethod.text and p.tool == "pdfplumber 0.11.10" for p in doc.pages)


# --- pictures inside DOCX / PPTX -------------------------------------------------------------


def test_docx_certificate_is_read_and_photo_dropped_unless_picture_ocr_is_off(samples):
    doc = read(samples["R28"], ocr=FakeOCR(lines=["성명: 편지우"]))
    assert {i.label: i.decision for i in doc.images} == {"그림 1": "photo", "그림 2": "ocr"}
    off = read(samples["R28"], embedded_images=False)
    assert {i.label: i.decision for i in off.images} == {"그림 1": "photo", "그림 2": "skipped"}
    assert not off.ocr_used and not off.needs_ocr


def test_a_picture_only_slide_is_read_as_a_page(samples):
    doc = read(samples["R30"], ocr=FakeOCR(lines=["작성자: 나도윤"]))
    methods = [p.method for p in doc.pages]
    assert methods == [ReadMethod.text] * 4 + [ReadMethod.ocr]
    assert doc.pages[4].reason == "그림만 있는 슬라이드"
    assert "슬라이드 5 (OCR)" in [b.label for b in doc.blocks if b.ocr]
    assert any(i.decision == "photo" for i in doc.images)  # the ID photo on slide 2


# --- legacy Office ---------------------------------------------------------------------------


def test_legacy_files_without_a_converter_say_so(samples, monkeypatch, tmp_path):
    with pytest.raises(ConverterMissing, match="변환기"):
        DocumentReader().read(samples["R29"].path.read_bytes(), "old.doc")
    monkeypatch.setenv("SOFFICE_CMD", str(tmp_path / "not-installed.exe"))  # a missing program
    with pytest.raises(ConverterMissing, match="LibreOffice"):
        read(samples["R29"], converter=LibreOfficeConverter())


@pytest.mark.skipif(not HAS_LIBREOFFICE, reason="LibreOffice (soffice) is not installed")
@pytest.mark.parametrize("sid", ["R29", "R31"])
def test_legacy_files_are_converted_and_read(samples, sid):
    doc = read(samples[sid], converter=LibreOfficeConverter())
    assert doc.format == samples[sid].format and doc.reading.converted_from == samples[sid].format
    assert any(t.startswith("LibreOffice") for t in doc.reading.tools)
    assert doc.metadata["작성자"] in ("탁서아", "곽민서")


# --- pieces ----------------------------------------------------------------------------------


def _certificate(width=600, height=800) -> Image.Image:
    from PIL import ImageFont

    img = Image.new("RGB", (width, height), (250, 250, 245))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for i in range(9):
        draw.text((40, 60 + i * 70), "자격번호 26-2001-000123 성명 홍길동", fill=(20, 20, 20), font=font)
        draw.line((40, 90 + i * 70, width - 40, 90 + i * 70), fill=(30, 30, 30), width=2)
    return img


def test_id_photo_check():
    portrait = Image.new("RGB", (300, 400), (220, 224, 230))
    draw = ImageDraw.Draw(portrait)
    draw.ellipse((90, 60, 210, 195), fill=(196, 160, 138))
    draw.rectangle((40, 250, 260, 400), fill=(52, 58, 82))
    assert check_picture(portrait, share=0.03).kind == "photo"
    assert check_picture(portrait, share=0.4).kind == "content"  # too large for an ID photo
    assert check_picture(_certificate(), share=0.08).kind == "content"  # portrait but text
    assert check_picture(Image.new("RGB", (90, 120)), share=0.01).kind == "small"


def test_ocr_lookalike_digits_are_fixed_only_in_number_runs():
    assert correct("휴대전화: 010-138l-O274") == "휴대전화: 010-1381-0274"
    assert correct("생년월일 1991.l2.12") == "생년월일 1991.12.12"
    assert correct("taemin.geum©example.org") == "taemin.geum@example.org"
    for unchanged in ("Taemin Geum", "B2B 사업", "ISO 9001", "Scanned with ScanApp"):
        assert correct(unchanged) == unchanged


def test_ocr_text_keeps_the_engines_order_and_joins_pieces_of_a_row():
    lines = (
        OcrLine("성명:", 0.9, (10, 10, 60, 30)),
        OcrLine("홍길동", 0.9, (80, 12, 140, 31)),  # same row, after a gap
        OcrLine("서지훈", 0.9, (300, 40, 360, 62)),  # a tilted line ends high ...
        OcrLine("책임님이", 0.9, (10, 45, 90, 66)),  # ... the next starts lower on the left
    )
    assert OcrResult(lines, "m", 0).text == "성명: 홍길동\n서지훈\n책임님이"


def test_a_failing_engine_holds_the_page_instead_of_failing_the_upload(samples):
    class Broken(FakeOCR):
        def recognize(self, image):
            raise RuntimeError("모델 파일이 없습니다")

    doc = read(samples["R18"], ocr=Broken())
    assert doc.needs_ocr and "OCR 실패: 모델 파일이 없습니다" in doc.pages[0].reason


def test_extraction_errors_stay_extraction_errors():
    with pytest.raises(ExtractionError):
        DocumentReader(ocr=FakeOCR()).read(b"\x89PNG\r\n\x1a\n broken", "x.png")


def test_reading_record_lists_every_tool(samples):
    doc = read(samples["R20"])
    assert doc.reading.tools == ("pdfplumber 0.11.10", "fake OCR")
    assert [p["method"] for p in doc.page_summary()] == ["text", "ocr"]
    assert re.fullmatch(r"\d+", str(doc.reading.elapsed_ms))


def test_reading_policy_rejects_unknown_values():
    with pytest.raises(ValueError):
        ReadingPolicy(mode="sometimes")
    with pytest.raises(ValueError):
        ReadingPolicy(sensitivity="paranoid")


def test_fake_ocr_reads_nothing_unless_told(samples):
    image = Image.new("L", (100, 50), 255)
    assert "fake OCR은 글자를 읽지 않습니다" in FakeOCR().recognize(image).text
    assert FakeOCR(lines=["a", "b"]).recognize(image).text == "a\nb"


def test_reading_makes_no_network_calls(samples, no_network):
    for i in ("R21", "R22", "R24", "R26", "R27", "R28", "R30"):
        read(samples[i])


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
