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


@dataclass(frozen=True)
class TextBlock:
    kind: BlockKind
    label: str  # fixed wording from the extractor ("1쪽 표 1", "작성자"), never file content
    text: str


@dataclass(frozen=True)
class PageInfo:
    """One PDF page or slide. `needs_ocr` means the page shows content that has no text layer."""

    number: int
    text_chars: int
    image_coverage: float = 0.0  # share of the page area covered by images, 0..1
    needs_ocr: bool = False


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    format: str
    blocks: tuple[TextBlock, ...]
    images_dropped: int = 0  # images are never extracted or forwarded, only counted
    pages: tuple[PageInfo, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def needs_ocr(self) -> bool:
        return any(p.needs_ocr for p in self.pages)

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


def render_blocks(blocks) -> str:
    """Labelled plain text, one section per block. Labels carry no file content."""
    return "\n\n".join(f"[{b.label}]\n{b.text}" for b in blocks if b.text)
