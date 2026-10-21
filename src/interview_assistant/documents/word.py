"""DOCX extractor on python-docx (MIT) for the package, lxml for the content.

python-docx's `Document.paragraphs` skips text boxes, headers it has not been asked for,
footnotes and comments, and does not tell hidden runs apart. So each WordprocessingML part is
walked directly: the main body in reading order (paragraphs and tables as separate blocks),
every header and footer part, footnotes, endnotes and comments. Runs marked hidden (w:vanish)
or coloured white on an unshaded background go to a hidden block. Deleted revisions and field
codes are not text a reader sees and are skipped.
"""

from __future__ import annotations

import io
from collections.abc import Iterator

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree

from interview_assistant.documents.base import BlockCollector, DocumentExtractor, ExtractionError
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.ooxml import count_images, parse_xml, read_properties
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml."
_PARTS = {
    _CT + "header+xml": (BlockKind.header, "머리글"),
    _CT + "footer+xml": (BlockKind.footer, "바닥글"),
    _CT + "footnotes+xml": (BlockKind.comment, "각주"),
    _CT + "endnotes+xml": (BlockKind.comment, "미주"),
    _CT + "comments+xml": (BlockKind.comment, "메모"),
}
_SKIP = frozenset({W + "delText", W + "instrText", W + "rPr", W + "pPr", MC + "Fallback"})
_CONTAINERS = frozenset(
    {W + "customXml", W + "footnote", W + "endnote", W + "comment", W + "ins", W + "moveTo"}
)
_WHITE = frozenset({"FFFFFF", "WHITE"})
_NO_FILL = frozenset({"", "AUTO", "FFFFFF"})


class DocxExtractor(DocumentExtractor):
    format = "docx"

    def __init__(self, *, min_text_chars: int = 30) -> None:
        """A document with fewer readable characters than this in its body and tables, but with
        pictures, is a scan pasted into Word and needs OCR."""
        self.min_text_chars = min_text_chars

    def extract(self, data: bytes, filename: str) -> ExtractedDocument:
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ExtractionError(f"DOCX를 읽을 수 없습니다: {type(exc).__name__}: {exc}") from None
        out = BlockCollector(filename, self.format)
        out.add_metadata(read_properties(data))

        body = document.element.body
        hidden: list[str] = []
        self._body(body, out, hidden)
        out.add(BlockKind.hidden, "본문 숨은 텍스트", "\n".join(hidden))

        package = document.part.package
        counters: dict[str, int] = {}
        links: list[str] = []
        for part in package.iter_parts():
            for rel in part.rels.values():
                if rel.reltype == RT.HYPERLINK and rel.is_external:
                    links.append(rel.target_ref)
            if part.content_type not in _PARTS:
                continue
            kind, label = _PARTS[part.content_type]
            root = parse_xml(part.blob)
            if root is None:
                continue
            counters[label] = counters.get(label, 0) + 1
            numbered = f"{label} {counters[label]}"
            part_hidden: list[str] = []
            text = "\n".join(_paragraphs(root, part_hidden))
            out.add(kind, numbered, text)
            out.add(BlockKind.hidden, f"{numbered} 숨은 텍스트", "\n".join(part_hidden))
        out.add_links("링크", links)
        out.images = count_images(data)

        chars = sum(len("".join(b.text.split())) for b in out.blocks_of(BlockKind.body, BlockKind.table))
        needs_ocr = chars < self.min_text_chars and count_images(data, "word/media/") > 0
        out.pages.append(PageInfo(1, chars, 0.0, needs_ocr))
        if needs_ocr:
            out.warnings.append("본문 텍스트 없이 그림만 있음, OCR 필요")
        return out.build()

    def _body(self, body: etree._Element, out: BlockCollector, hidden: list[str]) -> None:
        lines: list[str] = []
        tables = 0

        def flush() -> None:
            out.add(BlockKind.body, "본문", "\n".join(lines))
            lines.clear()

        for child in _blocks(body):
            if child.tag == W + "tbl":
                flush()
                tables += 1
                out.add(BlockKind.table, f"표 {tables}", _table(child, hidden))
            else:
                lines.append(_text(child, hidden))
        flush()


def _blocks(container: etree._Element) -> Iterator[etree._Element]:
    """Paragraphs and tables in order, unwrapping content controls, footnotes and comments."""
    for child in container:
        if child.tag in (W + "p", W + "tbl"):
            yield child
        elif child.tag == W + "sdt":
            content = child.find(W + "sdtContent")
            if content is not None:
                yield from _blocks(content)
        elif child.tag in _CONTAINERS:
            yield from _blocks(child)


def _paragraphs(root: etree._Element, hidden: list[str]) -> Iterator[str]:
    """Every top-level paragraph of a part; tables inside it are flattened row by row."""
    for block in _blocks(root):
        yield _table(block, hidden) if block.tag == W + "tbl" else _text(block, hidden)


def _table(tbl: etree._Element, hidden: list[str]) -> str:
    rows = []
    for tr in tbl.iter(W + "tr"):
        if tr.getparent() is not None and _owner_table(tr) is not tbl:
            continue  # rows of a nested table are read through their cell
        cells = [collapse(_text(tc, hidden)) for tc in tr.findall(W + "tc")]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _owner_table(el: etree._Element) -> etree._Element | None:
    parent = el.getparent()
    while parent is not None and parent.tag != W + "tbl":
        parent = parent.getparent()
    return parent


def _text(el: etree._Element, hidden: list[str]) -> str:
    """Visible text under `el`; hidden runs are appended to `hidden` as one entry.

    Text boxes and nested paragraphs start new lines.
    """
    out: list[str] = []
    secret: list[str] = []
    _walk(el, out, secret, el)
    if "".join(secret).strip():
        hidden.append("".join(secret))
    return "".join(out)


def _walk(el: etree._Element, out: list[str], hidden: list[str], top: etree._Element) -> None:
    for child in el:
        tag = child.tag
        if not isinstance(tag, str) or tag in _SKIP:
            continue
        if tag == W + "r":
            sink = hidden if _run_hidden(child) else out
            for node in child:
                if node.tag == W + "t":
                    sink.append(node.text or "")
                elif node.tag in (W + "tab", W + "ptab"):
                    sink.append(" ")
                elif node.tag in (W + "br", W + "cr"):
                    sink.append("\n")
                elif node.tag not in _SKIP:
                    _walk(node, out, hidden, top)  # drawings with text boxes
            continue
        if tag in (W + "p", W + "tbl", W + "tr") and child is not top and out and out[-1] != "\n":
            out.append("\n")
        if tag == W + "tc" and out and out[-1] not in ("\n", " "):
            out.append(" ")
        _walk(child, out, hidden, top)


def _run_hidden(run: etree._Element) -> bool:
    rpr = run.find(W + "rPr")
    if rpr is None:
        return False
    vanish = rpr.find(W + "vanish")
    if vanish is not None and vanish.get(W + "val", "true").lower() not in ("0", "false", "off"):
        return True
    color = rpr.find(W + "color")
    if color is None or (color.get(W + "val") or "").upper() not in _WHITE:
        return False
    return not _shaded(run)


def _shaded(run: etree._Element) -> bool:
    """True when the run, its paragraph or its table cell has a non-white background."""
    rpr = run.find(W + "rPr")
    if rpr is not None:
        highlight = rpr.find(W + "highlight")
        if highlight is not None and (highlight.get(W + "val") or "").lower() not in ("", "none", "white"):
            return True
    node: etree._Element | None = run
    while node is not None:
        for props in (W + "rPr", W + "pPr", W + "tcPr"):
            shd = node.find(f"{props}/{W}shd")
            if shd is not None and (shd.get(W + "fill") or "").upper() not in _NO_FILL:
                return True
        node = node.getparent()
    return False
