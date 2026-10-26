"""HWPX (OWPML, 한글 2014+) reader on lxml. Raw zone only.

An HWPX file is a zip: Contents/section*.xml hold the text, Contents/content.hpf the document
properties and the list of embedded files, Contents/header.xml the character styles, and
Preview/PrvText.txt a plain-text preview a viewer does not show. Elements are matched by local
name, so the 2011 and 2016 namespaces both work.

Read like a DOCX: body paragraphs in order with tables as separate blocks (cell by cell, nested
tables flattened into their cell), text boxes inline, headers and footers, footnotes and
endnotes, memos, hyperlink targets (fieldBegin HYPERLINK "Command"), properties (creator,
last saved by, title, subject, description, keywords) and change-tracking authors. Text a reader
does not see goes to hidden blocks: hidden comments (숨은 설명), runs whose character style is
white without a shade, and the preview text (it can be a stale copy of an earlier version).

Pictures are counted; with `reading`, each picture (BinData) is checked for an ID photo and read
by OCR as the policy says, and a document that is only pictures (a scan pasted into 한글) has
them read as its pages.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from interview_assistant.documents.base import BlockCollector, DocumentExtractor, ExtractionError
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.ooxml import local, parse_xml
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo, ReadMethod

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".wmf", ".emf")
_BOX_SHAPES = frozenset({"rect", "ellipse", "polygon", "curve", "arc", "connectLine", "textart"})
_NOTE_KINDS = {
    "header": (BlockKind.header, "머리글"),
    "footer": (BlockKind.footer, "바닥글"),
    "footNote": (BlockKind.comment, "각주"),
    "endNote": (BlockKind.comment, "미주"),
    "hiddenComment": (BlockKind.hidden, "숨은 설명"),
}
_SKIPPED_META = frozenset({"date", "createddate", "modifieddate", "language"})
HWPUNIT_PER_INCH = 7200


@dataclass
class _Picture:
    ref: str  # binaryItemIDRef
    width: int  # HWPUNIT, as placed
    height: int


@dataclass
class _Walk:
    white: frozenset[str]  # charPr ids whose text colour is white with no shade
    hidden: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    notes: list[tuple[BlockKind, str, str]] = field(default_factory=list)
    pictures: list[_Picture] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def label(self, base: str) -> str:
        self.counters[base] = self.counters.get(base, 0) + 1
        return f"{base} {self.counters[base]}"


class HwpxExtractor(DocumentExtractor):
    format = "hwpx"
    tool = "OWPML 읽기 (lxml)"

    def __init__(self, *, min_text_chars: int = 30) -> None:
        self.min_text_chars = min_text_chars

    def extract(self, data: bytes, filename: str, *, reading: Any = None) -> ExtractedDocument:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ExtractionError(f"HWPX를 읽을 수 없습니다: {exc}") from None
        out = BlockCollector(filename, self.format)
        with zf:
            names = zf.namelist()
            if any(n.startswith("META-INF/") and "encrypt" in n.lower() for n in names):
                from interview_assistant.documents.base import EncryptedDocument

                raise EncryptedDocument(
                    "암호가 걸린 HWPX 문서입니다. 한글에서 암호를 해제해 다시 저장한 파일을 올려 주세요."
                )
            manifest = _read(zf, "Contents/content.hpf")
            items = _metadata(manifest, out)
            header = _read(zf, "Contents/header.xml")
            walk = _Walk(_white_char_shapes(header))
            _track_authors(header, out)
            sections = sorted(
                (n for n in names if posixpath.basename(n).startswith("section") and n.endswith(".xml")),
                key=_section_number,
            )
            page_size: tuple[int, int] | None = None
            for name in sections:
                root = _read(zf, name)
                if root is None:
                    out.warnings.append(f"{name}: XML을 읽을 수 없음")
                    continue
                page_size = page_size or _page_size(root)
                _body(root, out, walk)
            for kind, label, text in walk.notes:
                out.add(kind, label, text)
            out.add(BlockKind.hidden, "본문 숨은 텍스트", "\n".join(walk.hidden))
            preview = _preview_text(zf, names)
            out.add(BlockKind.hidden, "미리보기 텍스트", preview)
            out.add_links("링크", walk.links)
            binaries = [n for n in names if n.lower().endswith(_IMAGE_SUFFIXES)]
            out.images = len(binaries)

            chars = sum(len("".join(b.text.split())) for b in out.blocks_of(BlockKind.body, BlockKind.table))
            pictures = _placed_pictures(zf, walk.pictures, items, page_size)
            picture_only = chars < self.min_text_chars and bool(pictures)
            if reading is None:
                out.pages.append(PageInfo(1, chars, 0.0, picture_only, ReadMethod.held if picture_only else ReadMethod.text))
                if picture_only:
                    out.warnings.append("본문 텍스트 없이 그림만 있음, OCR 필요")
                return out.build()
            read_pictures(out, reading, pictures, picture_only=picture_only, chars=chars, tool=self.tool)
        return out.build()


def read_pictures(
    out: BlockCollector,
    reading: Any,
    pictures: list[tuple[str, bytes, float | None]],
    *,
    picture_only: bool,
    chars: int,
    tool: str,
) -> None:
    """One page entry for a flowing document (DOCX, HWP, HWPX) and its pictures.

    A document that is only pictures is read like a scan: its pictures are its pages (OCR even
    when picture OCR is off, held in the text-only mode). Otherwise each picture goes through the
    ID-photo check and the picture setting.
    """
    from interview_assistant.documents.images import ImageError, open_image

    if picture_only:
        method, reason = reading.plan(has_text=False)
        if method is ReadMethod.held:
            out.pages.append(PageInfo(1, chars, 0.0, True, method, f"그림만 있는 문서: {reason}"))
            out.warnings.append(f"본문 텍스트 없이 그림만 있음: {reason}")
            return
    texts: list[str] = []
    confidences: list[tuple[int, float]] = []
    elapsed = 0
    failed = 0
    for label, blob, share in pictures:
        try:
            image = open_image(blob)
        except ImageError:
            continue
        result = reading.picture(image, label, share=share, force=picture_only)
        if result is None:
            failed += picture_only
            continue
        reading.check_confidence(label, result)
        elapsed += result.elapsed_ms
        if result.confidence is not None:
            confidences.append((len(result.text), result.confidence))
        if picture_only:
            texts.append(result.text)
        else:
            out.add(BlockKind.image_text, f"{label} (OCR)", result.text, ocr=True)
    confidence = (
        sum(n * c for n, c in confidences) / max(1, sum(n for n, _ in confidences))
        if confidences
        else None
    )
    if picture_only:
        held = not texts
        out.add(BlockKind.body, "그림 (OCR)", "\n\n".join(texts), ocr=True)
        ocr_tool = getattr(reading.ocr, "version", "")
        out.pages.append(
            PageInfo(
                1, chars, 0.0, held, ReadMethod.held if held else ReadMethod.ocr,
                "그림만 있는 문서" + (f"; {reading.problem or '그림에서 글자를 읽지 못함'}" if held else ""),
                "" if held else ocr_tool, confidence, elapsed or None,
            )
        )  # fmt: skip
        if held:
            out.warnings.append("그림만 있는 문서: OCR로 읽지 못해 보류")
        return
    out.pages.append(PageInfo(1, chars, 0.0, False, ReadMethod.text, "", tool))


# --- parts ------------------------------------------------------------------------------------


def _read(zf: zipfile.ZipFile, name: str) -> etree._Element | None:
    try:
        return parse_xml(zf.read(name))
    except KeyError:
        return None


def _section_number(name: str) -> int:
    digits = "".join(c for c in posixpath.basename(name) if c.isdigit())
    return int(digits) if digits else 0


def _metadata(manifest: etree._Element | None, out: BlockCollector) -> dict[str, str]:
    """Properties from content.hpf, and its manifest: item id -> href (BinData/image1.png)."""
    items: dict[str, str] = {}
    if manifest is None:
        return items
    fields: list[tuple[str, str]] = []
    for el in manifest.iter():
        name = local(el.tag)
        if name == "item" and el.get("id") and el.get("href"):
            items[el.get("id", "")] = el.get("href", "")
        elif name == "meta" and el.get("name"):
            key = el.get("name", "")
            if key.lower() not in _SKIPPED_META:
                fields.append((key, "".join(el.itertext())))
        elif name in ("title", "subject", "description", "creator", "keyword", "publisher"):
            parent = el.getparent()
            if parent is not None and local(parent.tag) == "metadata":
                fields.append((name, "".join(el.itertext())))
    out.add_metadata(("keywords" if k == "keyword" else k, v) for k, v in fields)
    return items


def _white_char_shapes(header: etree._Element | None) -> frozenset[str]:
    if header is None:
        return frozenset()
    white = set()
    for el in header.iter():
        if local(el.tag) != "charPr":
            continue
        color = (el.get("textColor") or "").upper().lstrip("#")
        shade = (el.get("shadeColor") or "none").upper().lstrip("#")
        if color in ("FFFFFF", "FFFFFFFF") and shade in ("NONE", "FFFFFF", "FFFFFFFF", ""):
            white.add(el.get("id", ""))
    return frozenset(white)


def _track_authors(header: etree._Element | None, out: BlockCollector) -> None:
    if header is None:
        return
    names = [el.get("name", "") for el in header.iter() if local(el.tag) == "trackChangeAuthor"]
    out.add(BlockKind.metadata, "변경 추적 작성자", "\n".join(n for n in names if n.strip()))


def _page_size(root: etree._Element) -> tuple[int, int] | None:
    for el in root.iter():
        if local(el.tag) == "pagePr":
            try:
                return int(el.get("width", "0")), int(el.get("height", "0"))
            except ValueError:
                return None
    return None


def _preview_text(zf: zipfile.ZipFile, names: list[str]) -> str:
    name = next((n for n in names if n.lower() == "preview/prvtext.txt"), None)
    if name is None:
        return ""
    raw = zf.read(name)
    for encoding in ("utf-8", "utf-16"):
        try:
            return raw.decode(encoding).replace("<", " ").replace(">", " ")
        except UnicodeDecodeError:
            continue
    return ""


def _placed_pictures(
    zf: zipfile.ZipFile,
    pictures: list[_Picture],
    items: dict[str, str],
    page: tuple[int, int] | None,
) -> list[tuple[str, bytes, float | None]]:
    out: list[tuple[str, bytes, float | None]] = []
    page_area = page[0] * page[1] if page and all(page) else 0
    for n, picture in enumerate(pictures, start=1):
        href = items.get(picture.ref) or next(
            (name for name in zf.namelist() if posixpath.splitext(posixpath.basename(name))[0] == picture.ref),
            None,
        )
        if not href:
            continue
        path = href if href in zf.namelist() else posixpath.join("Contents", href)
        try:
            blob = zf.read(path)
        except KeyError:
            continue
        share = picture.width * picture.height / page_area if page_area else None
        out.append((f"그림 {n}", blob, share))
    return out


# --- body -------------------------------------------------------------------------------------


def _body(root: etree._Element, out: BlockCollector, walk: _Walk) -> None:
    lines: list[str] = []

    def flush() -> None:
        out.add(BlockKind.body, "본문", "\n".join(lines))
        lines.clear()

    for p in _children(root, "p"):
        line: list[str] = []
        for run in _children(p, "run"):
            white = run.get("charPrIDRef", "") in walk.white
            for node in run:
                name = local(node.tag)
                if name == "t":
                    (walk.hidden if white else line).append(_t_text(node))
                elif name == "tbl":
                    lines.append("".join(line))
                    line.clear()
                    flush()
                    out.add(BlockKind.table, walk.label("표"), _table(node, walk))
                else:
                    text = _object(node, walk)
                    if text:
                        line.append("\n" + text + "\n")
        lines.append("".join(line))
    flush()


def _children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if local(c.tag) == name]


def _t_text(t: etree._Element) -> str:
    parts = [t.text or ""]
    for child in t:
        name = local(child.tag)
        if name in ("tab", "fwSpace", "nbSpace"):
            parts.append(" ")
        elif name == "lineBreak":
            parts.append("\n")
        parts.append(child.tail or "")
    return "".join(parts)


def _object(node: etree._Element, walk: _Walk) -> str:
    """Text an inline object shows in the body (text boxes, equations); notes, headers, links
    and pictures are recorded on `walk`."""
    name = local(node.tag)
    if name == "ctrl":
        for child in node:
            _control(child, walk)
        return ""
    if name == "pic":
        _picture(node, walk)
        return ""
    if name == "equation":
        return " ".join(s.text or "" for s in node.iter() if local(s.tag) == "script")
    if name in _BOX_SHAPES or name == "container":
        texts = []
        for child in node.iter():
            if local(child.tag) == "drawText":
                texts.append(_sublist_text(child, walk))
            elif local(child.tag) == "pic":
                _picture(child, walk)
        return "\n".join(t for t in texts if t)
    return ""


def _control(el: etree._Element, walk: _Walk) -> None:
    name = local(el.tag)
    if name in _NOTE_KINDS:
        kind, base = _NOTE_KINDS[name]
        text = _sublist_text(el, walk)
        if text.strip():
            walk.notes.append((kind, walk.label(base), text))
    elif name == "fieldBegin":
        field_type = (el.get("type") or "").upper()
        if field_type == "HYPERLINK":
            for param in el.iter():
                if local(param.tag) == "stringParam" and param.get("name") == "Command":
                    target = _command_target(param.text or "")
                    if target:
                        walk.links.append(target)
        elif field_type == "MEMO":
            text = _sublist_text(el, walk)
            if text.strip():
                walk.notes.append((BlockKind.comment, walk.label("메모"), text))


def _command_target(command: str) -> str:
    """'mailto\\:a@example.com;1;0;0;' -> 'mailto:a@example.com' (OWPML escapes ':' and ';')."""
    out, i = [], 0
    while i < len(command):
        c = command[i]
        if c == "\\" and i + 1 < len(command):
            out.append(command[i + 1])
            i += 2
            continue
        if c == ";":
            break
        out.append(c)
        i += 1
    return "".join(out).strip()


def _picture(node: etree._Element, walk: _Walk) -> None:
    ref = next((el.get("binaryItemIDRef") for el in node.iter() if local(el.tag) == "img"), None)
    size = next((el for el in node if local(el.tag) in ("curSz", "sz")), None)
    if ref:
        width = int(size.get("width", "0")) if size is not None else 0
        height = int(size.get("height", "0")) if size is not None else 0
        walk.pictures.append(_Picture(ref, width, height))


def _sublist_text(el: etree._Element, walk: _Walk) -> str:
    """Paragraphs under an object (header, note, text box), one per line; tables flattened."""
    lines = []
    for p in el.iter():
        if local(p.tag) != "p" or _inside_cell(p, el):
            continue
        line: list[str] = []
        for run in _children(p, "run"):
            white = run.get("charPrIDRef", "") in walk.white
            for node in run:
                name = local(node.tag)
                if name == "t":
                    (walk.hidden if white else line).append(_t_text(node))
                elif name == "tbl":
                    line.append(" " + _table(node, walk).replace("\n", " ") + " ")
                elif name == "ctrl":
                    for child in node:
                        if local(child.tag) == "fieldBegin":
                            _control(child, walk)
                elif name == "pic":
                    _picture(node, walk)
        lines.append("".join(line))
    return "\n".join(lines)


def _inside_cell(p: etree._Element, top: etree._Element) -> bool:
    parent = p.getparent()
    while parent is not None and parent is not top:
        if local(parent.tag) in ("tc", "drawText") and parent is not top:
            return True
        parent = parent.getparent()
    return False


def _table(tbl: etree._Element, walk: _Walk) -> str:
    rows = []
    for tr in _children(tbl, "tr"):
        cells = [collapse(_cell_text(tc, walk)) for tc in _children(tr, "tc")]
        if any(cells):
            rows.append(" | ".join(cells))
    caption = next((c for c in tbl if local(c.tag) == "caption"), None)
    if caption is not None:
        text = collapse(_sublist_text(caption, walk))
        if text:
            rows.insert(0, text)
    return "\n".join(rows)


def _cell_text(tc: etree._Element, walk: _Walk) -> str:
    sublist = next((c for c in tc if local(c.tag) == "subList"), tc)
    parts = []
    for p in _children(sublist, "p"):
        line: list[str] = []
        for run in _children(p, "run"):
            white = run.get("charPrIDRef", "") in walk.white
            for node in run:
                name = local(node.tag)
                if name == "t":
                    (walk.hidden if white else line).append(_t_text(node))
                elif name == "tbl":
                    line.append(" " + _table(node, walk).replace("\n", " ") + " ")
                else:
                    line.append(" " + _object(node, walk) + " ")
        parts.append("".join(line))
    return " ".join(parts)
