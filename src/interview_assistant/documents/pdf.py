"""PDF extractor on pdfplumber (MIT; pdfminer.six MIT, pypdfium2 Apache-2.0/BSD-3).

Per page: running text outside tables, each table cell by cell (so a value wrapped inside a
narrow cell stays together instead of interleaving with the neighbouring cell's lines), text a
viewer cannot see (white on a white page, sub-point size, off the page) in a separate hidden
block, link targets and annotation contents. Document properties come from the Info dictionary
and the XMP packet.

A page whose content is an image with (almost) no text layer is marked as needing OCR. No
text is produced for it: the PoC has no OCR, and the document is held back as a whole.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Sequence
from typing import Any

import pdfplumber
from pdfminer.pdftypes import resolve1

from interview_assistant.documents.base import (
    BlockCollector,
    DocumentExtractor,
    ExtractionError,
)
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.ooxml import local, parse_xml
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo

Obj = dict[str, Any]

# PDF Info keys -> keys METADATA_LABELS knows. /Creator is the authoring program, not a person.
_INFO_KEYS = {"Author": "author", "Creator": "creatortool", "Producer": "producer"}
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


class PdfExtractor(DocumentExtractor):
    format = "pdf"

    def __init__(self, *, min_text_chars: int = 30, scan_coverage: float = 0.5) -> None:
        """A page needs OCR when it has fewer than `min_text_chars` readable characters and
        either images cover at least `scan_coverage` of it or its text has no Unicode mapping."""
        self.min_text_chars = min_text_chars
        self.scan_coverage = scan_coverage

    def extract(self, data: bytes, filename: str) -> ExtractedDocument:
        out = BlockCollector(filename, self.format)
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                out.add_metadata((_INFO_KEYS.get(k, k), v) for k, v in _info(pdf).items())
                out.add_metadata(_xmp(pdf))
                for page in pdf.pages:
                    self._page(page, out)
        except ExtractionError:
            raise
        except Exception as exc:  # pdfminer raises a zoo of types for broken/encrypted files
            raise ExtractionError(f"PDF를 읽을 수 없습니다: {type(exc).__name__}: {exc}") from None
        return out.build()

    def _page(self, page: Any, out: BlockCollector) -> None:
        n = page.page_number
        chars: list[Obj] = page.chars
        fills = [r for r in page.rects if r.get("fill") and not _is_white(r.get("non_stroking_color"))]
        images: list[Obj] = page.images
        hidden_ids = {id(c) for c in chars if _is_hidden(c, page, fills, images)}

        visible = page.filter(lambda o: id(o) not in hidden_ids)
        tables = visible.find_tables()
        body = visible
        for table in tables:
            body = body.outside_bbox(table.bbox)
        out.add(BlockKind.body, f"{n}쪽", body.extract_text() or "")
        for i, table in enumerate(tables, start=1):
            rows = [" | ".join(collapse(unwrap_cell(cell or "")) for cell in row) for row in table.extract()]
            out.add(BlockKind.table, f"{n}쪽 표 {i}", "\n".join(r for r in rows if r.strip(" |")))
        if hidden_ids:
            hidden = page.filter(lambda o: id(o) in hidden_ids)
            out.add(BlockKind.hidden, f"{n}쪽 숨은 텍스트", hidden.extract_text() or "")

        annots: list[Obj] = page.annots
        out.add_links(f"{n}쪽 링크", (a.get("uri") or "" for a in annots))
        notes = [
            "\n".join(str(a[k]) for k in ("title", "contents") if a.get(k))
            for a in annots
            if not a.get("uri")
        ]
        out.add(BlockKind.comment, f"{n}쪽 주석", "\n".join(notes))

        readable = sum(1 for c in chars if c["text"].strip() and not _unmapped(c))
        unmapped = sum(1 for c in chars if _unmapped(c))
        coverage = _coverage(images, page)
        needs_ocr = readable < self.min_text_chars and (
            coverage >= self.scan_coverage or unmapped > 0
        )
        out.images += len(images)
        out.pages.append(PageInfo(n, readable, round(coverage, 3), needs_ocr))
        if needs_ocr:
            out.warnings.append(f"{n}쪽: 텍스트 레이어 없음, OCR 필요")
        elif unmapped:
            out.warnings.append(f"{n}쪽: 유니코드 매핑 없는 글자 {unmapped}개 제외")


_COMPLETE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_LOCAL_START = re.compile(r"[A-Za-z][A-Za-z0-9._%+-]*$")


def unwrap_cell(text: str) -> str:
    """Rejoin an e-mail address or URL that a narrow table cell wrapped onto the next line.

    PDF text has no trailing space at a line end, so "harin.kwon@exa" / "mple.com" would read
    as two words and slip past the e-mail pattern. Lines are glued without a space only when
    both sides are ASCII and the break is clearly inside one: after or before a connector
    (@ - / _ .), inside the domain of an unfinished address, or inside its local part.
    """
    lines = [line.strip() for line in text.split("\n")]
    out = [lines[0]]
    for line in lines[1:]:
        prev = out[-1]
        if prev and line and _inside_address(prev.rsplit(" ", 1)[-1], line.split(" ", 1)[0]):
            out[-1] = prev + line
        else:
            out.append(line)
    return "\n".join(out)


def _inside_address(tail: str, head: str) -> bool:
    if not (tail.isascii() and head.isascii()):
        return False
    if tail[-1] in "@-/_" or head[0] in "@._-":
        return True
    if "@" in tail:  # domain part continues
        return not _COMPLETE_EMAIL.match(tail)
    if "://" in tail or tail.startswith("www."):
        return True
    # local part continues: "harin.kw" / "on@example.com"
    return "@" in head and bool(_LOCAL_START.match(tail)) and bool(_COMPLETE_EMAIL.match(tail + head))


def _info(pdf: Any) -> dict[str, str]:
    out = {}
    for key, value in (pdf.metadata or {}).items():
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str):
            out[str(key)] = value
    return out


def _xmp(pdf: Any) -> list[tuple[str, str]]:
    """Leaf values of the XMP packet as ("prefix:name", value). Word and Acrobat write the
    author here as well as in the Info dictionary."""
    try:
        stream = resolve1(pdf.doc.catalog.get("Metadata"))
        data = stream.get_data() if stream is not None else None
    except Exception:
        return []
    root = parse_xml(data) if data else None
    if root is None:
        return []
    out: list[tuple[str, str]] = []
    for el in root.iter():
        if local(el.tag) == "Description":
            for attr, value in el.attrib.items():
                if not attr.startswith(f"{{{_RDF}}}") and value.strip():
                    out.append((local(attr), value))
        elif len(el) == 0 and el.text and el.text.strip():
            prop = el
            while prop is not None and str(prop.tag).startswith(f"{{{_RDF}}}"):
                prop = prop.getparent()
            if prop is not None:
                out.append((local(prop.tag), el.text))
    return out


def _unmapped(char: Obj) -> bool:
    return char["text"].startswith("(cid:")


def _is_white(color: Any) -> bool:
    if color is None or isinstance(color, str):
        return False
    try:
        values = tuple(float(v) for v in (color if isinstance(color, Sequence) else (color,)))
    except (TypeError, ValueError):
        return False
    if len(values) in (1, 3):
        return min(values) >= 0.95
    if len(values) == 4:  # CMYK
        return max(values) <= 0.05
    return False


def _inside(obj: Obj, x: float, y: float) -> bool:
    return obj["x0"] <= x <= obj["x1"] and obj["top"] <= y <= obj["bottom"]


def _is_hidden(char: Obj, page: Any, fills: list[Obj], images: list[Obj]) -> bool:
    # Space glyphs are judged like letters: the spaces of a white line belong to the hidden
    # text, otherwise its words run together ("추천인이서준선배") and patterns lose boundaries.
    x = (char["x0"] + char["x1"]) / 2
    y = (char["top"] + char["bottom"]) / 2
    if not (0 <= x <= page.width and 0 <= y <= page.height):
        return True  # outside the visible page
    if char.get("size", 10) < 1:
        return True  # sub-point text
    if _is_white(char.get("non_stroking_color")):
        # White text is visible on a dark box or a picture (sidebars, banners).
        return not any(_inside(o, x, y) for o in (*fills, *images))
    return False


def _coverage(images: list[Obj], page: Any) -> float:
    area = page.width * page.height
    if not images or area <= 0:
        return 0.0
    clip: Callable[[float, float], float] = lambda v, hi: max(0.0, min(v, hi))  # noqa: E731
    covered = sum(
        (clip(i["x1"], page.width) - clip(i["x0"], page.width))
        * (clip(i["bottom"], page.height) - clip(i["top"], page.height))
        for i in images
    )
    return min(1.0, covered / area)
