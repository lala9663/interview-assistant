"""PDF extractor on pdfplumber (MIT; pdfminer.six MIT, pypdfium2 Apache-2.0/BSD-3).

Per page: running text outside tables, each table cell by cell (so a value wrapped inside a
narrow cell stays together instead of interleaving with the neighbouring cell's lines), text a
viewer cannot see (white on a white page, sub-point size, off the page) in a separate hidden
block, link targets and annotation contents. Document properties come from the Info dictionary
and the XMP packet. Letter-spaced lines (자간을 넓힌 머리글 "권 하 린") are read from the glyph
positions back into words ("권하린") before the text goes anywhere.

A page whose content is an image with (almost) no text layer needs OCR. Without `reading` it is
only marked (`needs_ocr`) and the document is held back as a whole. With `reading`
(documents/reading.py) each page is planned: its text layer when usable, OCR of the rendered
page when there is none or when the layer is garbled (quality.py; the garbled text, hidden text
included, is dropped), always OCR or text only as the policy says. On a page read as text,
pictures smaller than half the page are checked for an ID photo and read by OCR as the policy
says (a larger picture behind a text layer is a background or the scan of a searchable PDF).
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Sequence
from itertools import pairwise
from operator import itemgetter
from typing import Any

import pdfplumber
from pdfminer.pdftypes import resolve1
from pdfplumber.utils import cluster_objects, extract_text

from interview_assistant.documents.base import (
    BlockCollector,
    DocumentExtractor,
    ExtractionError,
)
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.ooxml import local, parse_xml
from interview_assistant.documents.quality import assess
from interview_assistant.documents.render import PdfRenderer
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo, ReadMethod

Obj = dict[str, Any]

# PDF Info keys -> keys METADATA_LABELS knows. /Creator is the authoring program, not a person.
_INFO_KEYS = {"Author": "author", "Creator": "creatortool", "Producer": "producer"}
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


class PdfExtractor(DocumentExtractor):
    format = "pdf"

    def __init__(self, *, min_text_chars: int = 30, scan_coverage: float = 0.5, **_: Any) -> None:
        """A page needs OCR when it has fewer than `min_text_chars` readable characters and
        either images cover at least `scan_coverage` of it or its text has no Unicode mapping."""
        from interview_assistant.documents.reading import package_version

        self.min_text_chars = min_text_chars
        self.scan_coverage = scan_coverage
        self.tool = package_version("pdfplumber")
        self.model = self.tool

    async def warm_up(self) -> None:
        return None

    def extract(self, data: bytes, filename: str, *, reading: Any = None) -> ExtractedDocument:
        out = BlockCollector(filename, self.format)
        renderer = PdfRenderer(data) if reading is not None else None
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                out.add_metadata((_INFO_KEYS.get(k, k), v) for k, v in _info(pdf).items())
                out.add_metadata(_xmp(pdf))
                for page in pdf.pages:
                    self._page(page, out, reading, renderer)
        except ExtractionError:
            raise
        except Exception as exc:  # pdfminer raises a zoo of types for broken/encrypted files
            raise ExtractionError(f"PDF를 읽을 수 없습니다: {type(exc).__name__}: {exc}") from None
        finally:
            if renderer is not None:
                renderer.close()
        return out.build()

    def _page(
        self, page: Any, out: BlockCollector, reading: Any = None, renderer: PdfRenderer | None = None
    ) -> None:
        n = page.page_number
        start = len(out.blocks)
        chars: list[Obj] = page.chars
        fills = [r for r in page.rects if r.get("fill") and not _is_white(r.get("non_stroking_color"))]
        images: list[Obj] = page.images
        hidden_ids = {id(c) for c in chars if _is_hidden(c, page, fills, images)}

        visible = page.filter(lambda o: id(o) not in hidden_ids)
        tables = visible.find_tables()
        body = visible
        for table in tables:
            body = body.outside_bbox(table.bbox)
        out.add(BlockKind.body, f"{n}쪽", _text(body.chars))
        for i, table in enumerate(tables, start=1):
            rows = [" | ".join(collapse(unwrap_cell(cell)) for cell in row) for row in _cells(table)]
            out.add(BlockKind.table, f"{n}쪽 표 {i}", "\n".join(r for r in rows if r.strip(" |")))
        if hidden_ids:
            hidden = page.filter(lambda o: id(o) in hidden_ids)
            out.add(BlockKind.hidden, f"{n}쪽 숨은 텍스트", _text(hidden.chars))

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
        if reading is None or renderer is None:
            out.pages.append(PageInfo(n, readable, round(coverage, 3), needs_ocr))
            if needs_ocr:
                out.warnings.append(f"{n}쪽: 텍스트 레이어 없음, OCR 필요")
            elif unmapped:
                out.warnings.append(f"{n}쪽: 유니코드 매핑 없는 글자 {unmapped}개 제외")
            return

        layer = [b for b in out.blocks[start:] if b.kind in (BlockKind.body, BlockKind.table)]
        quality = assess("\n".join(b.text for b in layer)) if layer else None
        method, reason = reading.plan(has_text=not needs_ocr, quality=quality)
        garbled = quality is not None and quality.garbled(reading.policy.sensitivity)
        info = dict(
            number=n,
            text_chars=readable,
            image_coverage=round(coverage, 3),
            garbled=None if quality is None else round(quality.ratio, 3),
        )
        if method is ReadMethod.text:
            out.pages.append(PageInfo(**info, method=method, tool=self.tool))
            if unmapped:
                out.warnings.append(f"{n}쪽: 유니코드 매핑 없는 글자 {unmapped}개 제외")
            self._pictures(page, images, out, reading, renderer)
            return
        # OCR or held: the text layer's running text goes; garbled text goes entirely (hidden
        # text in the same broken font too). Links, notes and properties are kept.
        dropped = {BlockKind.body, BlockKind.table} | ({BlockKind.hidden} if garbled else set())
        out.blocks[start:] = [b for b in out.blocks[start:] if b.kind not in dropped]
        if garbled:
            out.warnings.append(f"{n}쪽: 텍스트 층이 깨져 버림 ({quality.describe()})")  # type: ignore[union-attr]
        if method is ReadMethod.ocr:
            result, problem = reading.read(renderer.page(n - 1, reading.policy.dpi))
            if result is not None:
                out.add(BlockKind.body, f"{n}쪽 (OCR)", result.text, ocr=True)
                reading.check_confidence(f"{n}쪽", result)
                out.pages.append(
                    PageInfo(
                        **info, method=ReadMethod.ocr, reason=reason,
                        tool=getattr(reading.ocr, "version", "") or result.model,
                        confidence=result.confidence, elapsed_ms=result.elapsed_ms,
                    )
                )  # fmt: skip
                return
            reason = f"{reason}; {problem}"
        out.pages.append(PageInfo(**info, needs_ocr=True, method=ReadMethod.held, reason=reason))
        out.warnings.append(f"{n}쪽: {reason}, 처리 보류")

    def _pictures(
        self, page: Any, images: list[Obj], out: BlockCollector, reading: Any, renderer: PdfRenderer
    ) -> None:
        area = page.width * page.height
        for k, image in enumerate(images, start=1):
            share = _coverage([image], page)
            if share >= self.scan_coverage or area <= 0:
                continue  # a background, or the scan behind a searchable PDF's text layer
            bbox = (image["x0"], image["top"], image["x1"], image["bottom"])
            picture = renderer.crop(page.page_number - 1, reading.policy.dpi, bbox)
            label = f"{page.page_number}쪽 그림 {k}"
            result = reading.picture(picture, label, share=share)
            if result is not None:
                reading.check_confidence(label, result)
                out.add(BlockKind.image_text, f"{label} (OCR)", result.text, ocr=True)


def _text(chars: list[Obj]) -> str:
    return extract_text(close_letter_spacing(chars)) or ""


def _cells(table: Any) -> list[list[str]]:
    """`table.extract()`, with each cell read through `close_letter_spacing` on its own (so
    closing a gap in one cell never moves text into the next)."""
    chars: list[Obj] = table.page.chars
    rows = []
    for row in table.rows:
        in_row = [c for c in chars if _centre_in(c, row.bbox)]
        cells = [[c for c in in_row if _centre_in(c, cell)] if cell else [] for cell in row.cells]
        rows.append([_text(cell_chars) for cell_chars in cells])
    return rows


def _centre_in(char: Obj, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox  # same test as pdfplumber's Table.extract
    x = (char["x0"] + char["x1"]) / 2
    y = (char["top"] + char["bottom"]) / 2
    return x0 <= x < x1 and top <= y < bottom


# pdfplumber's default tolerances: a gap wider than _X_TOLERANCE starts a new word, chars whose
# tops are within _Y_TOLERANCE are one line.
_X_TOLERANCE = 3.0
_Y_TOLERANCE = 3.0


def close_letter_spacing(chars: list[Obj]) -> list[Obj]:
    """Close the gaps of letter-spaced (자간 넓힌) text so it reads as words again.

    A heading drawn with extra character spacing comes out as "권 하 린 · 이 력 서", because
    every gap is wider than the word tolerance. Per line, a run of at least three glyphs with
    no space glyph between them and even gaps (each wider than the tolerance, at most one em,
    all within 15% of each other) is letter spacing, provided the run is not glued to a
    neighbouring glyph; so is a two-glyph run with the same spacing on such a line. Their gaps
    are closed by moving the rest of the line left. Space glyphs and wider gaps stay word
    breaks, so the line reads "권하린 · 이력서".

    Ordinary text has no such runs and comes back as the same objects; text set without space
    glyphs (words apart only by a gap) is not touched either, because a run must not touch a
    tightly set word.
    """
    moved: dict[int, Obj] = {}
    upright = [c for c in chars if c.get("upright", True)]
    for line in cluster_objects(upright, itemgetter("top"), _Y_TOLERANCE):
        line = sorted(line, key=itemgetter("x0"))
        closing = _letter_gaps(line)
        shift = 0.0
        for i, char in enumerate(line):
            if i in closing:
                shift += char["x0"] - line[i - 1]["x1"]
            if shift:
                moved[id(char)] = {**char, "x0": char["x0"] - shift, "x1": char["x1"] - shift}
    return [moved.get(id(c), c) for c in chars] if moved else chars


def _letter_gaps(line: list[Obj]) -> set[int]:
    """Indices of glyphs whose gap to the previous glyph is letter spacing (see above)."""
    gaps: list[float] = [b["x0"] - a["x1"] for a, b in pairwise(line)]
    spaced = [
        not a["text"].isspace()
        and not b["text"].isspace()
        and abs(a["size"] - b["size"]) < 0.5
        and _X_TOLERANCE < gap <= a["size"]
        for (a, b), gap in zip(pairwise(line), gaps, strict=True)
    ]

    def tight(k: int) -> bool:  # gap k (glyph k to k + 1) glues two glyphs into one word
        if not 0 <= k < len(gaps) or gaps[k] > _X_TOLERANCE:
            return False
        return not (line[k]["text"].isspace() or line[k + 1]["text"].isspace())

    runs: list[tuple[int, int, float, float]] = []  # gaps i..j (glyphs i..j + 1), their range
    i = 0
    while i < len(gaps):
        if not spaced[i]:
            i += 1
            continue
        j, low, high = i, gaps[i], gaps[i]
        while j + 1 < len(gaps) and spaced[j + 1]:
            lo, hi = min(low, gaps[j + 1]), max(high, gaps[j + 1])
            if not _even(lo, hi):
                break
            j, low, high = j + 1, lo, hi
        if not tight(i - 1) and not tight(j + 1):
            runs.append((i, j, low, high))
        i = j + 1

    # Three glyphs or more prove the line is letter-spaced; then a two-letter word with the
    # same spacing ("박 사") is closed too. A lone pair is left alone.
    proven = [(low, high) for i, j, low, high in runs if j > i]
    closing: set[int] = set()
    for i, j, low, high in runs:
        if j > i or any(_even(min(low, lo), max(high, hi)) for lo, hi in proven):
            closing.update(range(i + 1, j + 2))
    return closing


def _even(low: float, high: float) -> bool:
    return high - low <= max(0.5, 0.15 * low)


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
