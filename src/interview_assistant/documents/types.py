"""Extraction results: every piece of text a file carries, labelled by where it came from.

Raw zone only. An `ExtractedDocument` still holds the original values; it reaches an LLM only
through `interview_assistant.deid.documents.deidentify_document`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class BlockKind(str, enum.Enum):
    filename = "filename"  # the name the file was uploaded with
    metadata = "metadata"  # document properties: author, title, last modified by, company ...
    body = "body"  # running text of a page, slide or document
    table = "table"  # one table, a row per line, cells joined with " | "
    header = "header"
    footer = "footer"
    notes = "notes"  # slide speaker notes
    comment = "comment"  # review comments, footnotes, PDF annotations
    link = "link"  # hyperlink targets (mailto:, tel:, https:)
    hidden = "hidden"  # in the file but not visible: white or zero-size text, display:none, off-slide
    image_text = "image_text"  # text OCR read in a picture placed in the document (certificate, capture)


class ReadMethod(str, enum.Enum):
    text = "text"  # the file's own text (PDF text layer, DOCX/HWP content ...)
    ocr = "ocr"  # rendered and read by the OCR engine
    held = "held"  # needs OCR but was not read (text-only setting, OCR unavailable): not sent


@dataclass(frozen=True)
class TextBlock:
    kind: BlockKind
    label: str  # fixed wording from the extractor ("1쪽 표 1", "작성자"), never file content
    text: str
    ocr: bool = False  # read by OCR: may hold misread identifiers, de-identified with tolerance


@dataclass(frozen=True)
class PageInfo:
    """One PDF page, slide or image (one entry for a whole DOCX/HWP/HTML file).

    `needs_ocr`: the page shows content without a usable text layer and was not OCR'd, so the
    document is held. `method`, `tool`, `confidence` record how the page was read; `reason` says
    why OCR was needed (or why the page is held).
    """

    number: int
    text_chars: int
    image_coverage: float = 0.0  # share of the page area covered by images, 0..1
    needs_ocr: bool = False
    method: ReadMethod = ReadMethod.text
    reason: str = ""
    tool: str = ""
    confidence: float | None = None  # mean OCR confidence (0..1)
    elapsed_ms: int | None = None
    garbled: float | None = None  # share of suspicious characters in the text layer (quality.py)


@dataclass(frozen=True)
class ImageInfo:
    """A picture inside a document and what was done with it. The picture itself is never kept.

    decision: photo (looks like an ID photo: dropped without OCR), ocr (its text is in an
    image_text block), skipped (picture OCR is off), small (too small to hold text), failed.
    """

    label: str
    width: int
    height: int
    decision: str
    confidence: float | None = None
    elapsed_ms: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class ReadingRecord:
    """The reading settings and tools a document was read with (stored per application)."""

    mode: str  # auto | always_ocr | text_only
    embedded_images: bool
    sensitivity: str
    tools: tuple[str, ...]  # every tool that produced text, with its version
    revision: int | None = None  # model-settings revision the reading ran under
    elapsed_ms: int = 0
    converted_from: str | None = None  # "doc" / "ppt" when a converter made the file read

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "embedded_images": self.embedded_images,
            "sensitivity": self.sensitivity,
            "tools": list(self.tools),
            "revision": self.revision,
            "elapsed_ms": self.elapsed_ms,
            "converted_from": self.converted_from,
        }


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    format: str
    blocks: tuple[TextBlock, ...]
    images_dropped: int = 0  # images are never extracted or forwarded, only counted
    pages: tuple[PageInfo, ...] = ()
    warnings: tuple[str, ...] = ()
    images: tuple[ImageInfo, ...] = ()
    reading: ReadingRecord | None = None

    @property
    def needs_ocr(self) -> bool:
        return any(p.needs_ocr for p in self.pages)

    @property
    def ocr_used(self) -> bool:
        return any(b.ocr for b in self.blocks)

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.needs_ocr]

    def blocks_of(self, *kinds: BlockKind) -> list[TextBlock]:
        return [b for b in self.blocks if b.kind in kinds]

    @property
    def metadata(self) -> dict[str, str]:
        return {b.label: b.text for b in self.blocks if b.kind is BlockKind.metadata}

    def render(self) -> str:
        return render_blocks(self.blocks)

    def page_summary(self) -> list[dict]:
        """Per page: how it was read. What the review report and the application record show."""
        return [
            {
                "page": p.number,
                "method": p.method.value,
                "reason": p.reason or None,
                "tool": p.tool or None,
                "confidence": None if p.confidence is None else round(p.confidence, 3),
                "elapsed_ms": p.elapsed_ms,
                "text_chars": p.text_chars,
            }
            for p in self.pages
        ]


def render_blocks(blocks) -> str:
    """Labelled plain text, one section per block. Labels carry no file content."""
    return "\n\n".join(f"[{b.label}]\n{b.text}" for b in blocks if b.text)
