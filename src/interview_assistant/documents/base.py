"""Extractor interface, file-type detection and the helper every extractor fills in."""

from __future__ import annotations

import io
import re
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping

from interview_assistant.documents.normalize import normalize_text
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo, TextBlock


class ExtractionError(Exception):
    """The file could not be read (corrupt, encrypted, wrong type)."""


class UnsupportedFormat(ExtractionError):
    """No extractor for this file type (HWP, legacy .doc/.ppt, images ...)."""


class DocumentExtractor(ABC):
    """Turns one file into labelled text blocks. Implementations must not use the network.

    Contract: return every piece of text the file would show or hand to a text reader (body,
    tables, headers and footers, notes, link targets, properties, the file name), put text a
    viewer would not see into `hidden` blocks, count images instead of extracting them, and mark
    pages without a text layer as needing OCR instead of producing text for them.
    """

    format: str

    @abstractmethod
    def extract(self, data: bytes, filename: str) -> ExtractedDocument: ...


class BlockCollector:
    """Accumulates blocks in reading order; normalises text and skips empty blocks."""

    def __init__(self, filename: str, format: str) -> None:
        self.filename = normalize_text(filename)
        self.format = format
        self.blocks: list[TextBlock] = []
        self.pages: list[PageInfo] = []
        self.warnings: list[str] = []
        self.images = 0
        self.add(BlockKind.filename, "파일명", filename)

    def add(self, kind: BlockKind, label: str, text: str) -> None:
        text = normalize_text(text)
        if text:
            self.blocks.append(TextBlock(kind, label, text))

    def add_links(self, label: str, targets: Iterable[str]) -> None:
        seen: list[str] = []
        for target in targets:
            target = (target or "").strip()
            if target and target not in seen:
                seen.append(target)
        self.add(BlockKind.link, label, "\n".join(seen))

    def add_metadata(self, fields: Mapping[str, str] | Iterable[tuple[str, str]]) -> None:
        """Standard keys get a fixed label; anything else goes under "기타 속성" as "key: value",
        because a custom property's name is file content too."""
        items = fields.items() if isinstance(fields, Mapping) else fields
        for key, value in items:
            value = normalize_text(str(value or ""))
            if (
                not value
                or key.lower() in SKIPPED_KEYS
                or value.lower() in _PLACEHOLDER_VALUES
                or _looks_like_timestamp(key, value)
            ):
                continue
            label = METADATA_LABELS.get(key.lower())
            if label is None:
                self.add(BlockKind.metadata, "기타 속성", f"{key}: {value}")
            else:
                self.add(BlockKind.metadata, label, value)

    def blocks_of(self, *kinds: BlockKind) -> list[TextBlock]:
        return [b for b in self.blocks if b.kind in kinds]

    def build(self) -> ExtractedDocument:
        return ExtractedDocument(
            filename=self.filename,
            format=self.format,
            blocks=tuple(self.blocks),
            images_dropped=self.images,
            pages=tuple(self.pages),
            warnings=tuple(self.warnings),
        )


# Lower-cased property names (PDF Info, OOXML core/app properties, HTML meta) -> label.
METADATA_LABELS = {
    "author": "작성자",
    "creator": "작성자",  # OOXML dc:creator; PDF /Creator is mapped below by the PDF extractor
    "dc:creator": "작성자",
    "lastmodifiedby": "마지막 수정자",
    "title": "제목",
    "dc:title": "제목",
    "subject": "주제",
    "dc:subject": "주제",
    "keywords": "키워드",
    "description": "설명",
    "dc:description": "설명",
    "category": "범주",
    "contentstatus": "상태",
    "identifier": "식별자",
    "language": "언어",
    "version": "버전",
    "company": "회사",
    "manager": "관리자",
    "template": "서식 파일",
    "hyperlinkbase": "하이퍼링크 기준 주소",
}

# Properties that describe the software, not a person ("Microsoft Word 15", revision counters).
# Not extracted: they carry nothing for the LLM, and company dictionaries turn "Microsoft" into
# a company token.
SKIPPED_KEYS = frozenset(
    "application appversion generator progid originator producer creatortool revision totaltime "
    "docsecurity scalecrop linksuptodate shareddoc hyperlinkschanged".split()
)

# Defaults some writers fill in (ReportLab, PDF trapping flag); not content.
_PLACEHOLDER_VALUES = frozenset(
    {"(unspecified)", "unspecified", "anonymous", "untitled", "false", "true", "unknown"}
)
_TIMESTAMP_KEY = re.compile(r"date|created|modified|printed|time", re.I)
_TIMESTAMP_VALUE = re.compile(r"^(?:D:)?\d{4}-?\d{2}-?\d{2}(?:[T ]?\d{2}:?\d{2}(?::?\d{2})?.*)?$")


def _looks_like_timestamp(key: str, value: str) -> bool:
    return bool(_TIMESTAMP_KEY.search(key) and _TIMESTAMP_VALUE.match(value))


# --- file type detection ---------------------------------------------------------------------

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # HWP 5, legacy .doc/.ppt/.xls
_HTML_SNIFF = re.compile(rb"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]|<meta\s", re.I)
_HTML_EXTENSIONS = (".html", ".htm", ".xhtml")


def detect_format(data: bytes, filename: str = "") -> str:
    """'pdf', 'docx', 'pptx' or 'html' from the content (not just the extension).

    Raises UnsupportedFormat for anything else, naming HWP explicitly since it is common in
    Korean applications and out of scope for the PoC.
    """
    head = data[:1024]
    if b"%PDF-" in head:
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                mimetype = zf.read("mimetype")[:64] if "mimetype" in names else b""
        except zipfile.BadZipFile as exc:
            raise ExtractionError(f"손상된 압축 파일: {exc}") from None
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        if b"hwp" in mimetype or any(n.startswith("Contents/section") for n in names):
            raise UnsupportedFormat("HWPX(한글) 파일은 아직 지원하지 않습니다")
        raise UnsupportedFormat("지원하지 않는 압축 문서 형식입니다")
    if data[:8] == _OLE:
        if filename.lower().endswith(".hwp"):
            raise UnsupportedFormat("HWP(한글) 파일은 아직 지원하지 않습니다")
        raise UnsupportedFormat("HWP 또는 구형 오피스 파일(.doc/.ppt)은 아직 지원하지 않습니다")
    if filename.lower().endswith(_HTML_EXTENSIONS) or _HTML_SNIFF.search(head):
        return "html"
    raise UnsupportedFormat("지원하지 않는 파일 형식입니다")


def default_extractors() -> dict[str, DocumentExtractor]:
    from interview_assistant.documents.pdf import PdfExtractor
    from interview_assistant.documents.powerpoint import PptxExtractor
    from interview_assistant.documents.webpage import HtmlExtractor
    from interview_assistant.documents.word import DocxExtractor

    return {
        "pdf": PdfExtractor(),
        "docx": DocxExtractor(),
        "pptx": PptxExtractor(),
        "html": HtmlExtractor(),
    }


def extract_document(
    data: bytes,
    filename: str,
    extractors: Mapping[str, DocumentExtractor] | None = None,
) -> ExtractedDocument:
    """Detect the format and run the matching extractor. Pass `extractors` to swap one out."""
    fmt = detect_format(data, filename)
    registry = default_extractors() if extractors is None else extractors
    extractor = registry.get(fmt)
    if extractor is None:
        raise UnsupportedFormat(f"'{fmt}' 형식의 추출기가 등록되어 있지 않습니다")
    return extractor.extract(data, filename)
