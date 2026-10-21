"""HTML extractor on BeautifulSoup (MIT) with the standard library parser.

Reads <title> and <meta> as properties, link targets (mailto:, tel:) as links, <header> and
<footer> as such, tables cell by cell, and the rest as body text in reading order. Elements a
browser would not show (display:none, visibility:hidden, white or zero-size text, the hidden
attribute, inline or via simple <style> rules) go to a hidden block. Scripts, styles, comments
and images (with their alt text) are dropped; images are counted. Nothing is fetched: external
stylesheets, images and frames stay unresolved.

Korean pages often declare EUC-KR; it is decoded as CP949, its superset, so characters such as
"똠" survive.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction

from interview_assistant.documents.base import BlockCollector, DocumentExtractor
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo

_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)
_KOREAN_LEGACY = {"euc-kr", "euc_kr", "ks_c_5601-1987", "ksc5601", "x-windows-949", "windows-949", "cp949", "uhc"}

_BLOCK_TAGS = frozenset(
    """address article aside blockquote caption dd details div dl dt fieldset figcaption figure
    footer form h1 h2 h3 h4 h5 h6 header hr legend li main nav ol p pre section summary table
    tbody td tfoot th thead tr ul""".split()
)
_DROP_TAGS = ("script", "style", "noscript", "template", "head", "iframe", "frame", "frameset")
_IMAGE_TAGS = ("img", "svg", "picture", "object", "embed", "canvas", "video")

_HIDING = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|"
    r"font-size\s*:\s*(?:0?\.\d+|0)[a-z%]*\s*(?:;|$|!)|font-size\s*:\s*1(?:px|pt)\s*(?:;|$|!)|"
    r"opacity\s*:\s*0(?:\.0+)?\s*(?:;|$|!)|"
    r"(?:left|top|text-indent)\s*:\s*-\d{3,}",
    re.I,
)
_SKIP_META = frozenset({"viewport", "theme-color", "format-detection", "robots", "referrer", "color-scheme"})
_WHITE_TEXT = re.compile(
    r"(?<![-\w])color\s*:\s*(?:#fff(?:fff)?\b|white\b|rgba?\(\s*255\s*,\s*255\s*,\s*255)", re.I
)
_BACKGROUND = re.compile(r"background(?:-color)?\s*:\s*(?!\s*(?:#fff(?:fff)?\b|white\b|transparent|none))", re.I)
_CSS_RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}")
_BG_IMAGE = re.compile(r"background(?:-image)?\s*:[^;]*url\(", re.I)


class HtmlExtractor(DocumentExtractor):
    format = "html"

    def __init__(self, *, min_text_chars: int = 30) -> None:
        self.min_text_chars = min_text_chars

    def extract(self, data: bytes, filename: str) -> ExtractedDocument:
        out = BlockCollector(filename, self.format)
        soup = BeautifulSoup(decode_html(data), "html.parser")

        title = soup.find("title")
        if title is not None:
            out.add_metadata([("title", title.get_text())])
        for meta in soup.find_all("meta"):
            key = str(meta.get("name") or meta.get("property") or meta.get("itemprop") or "")
            if key and meta.get("content") and key.lower() not in _SKIP_META:
                out.add_metadata([(key, str(meta["content"]))])

        hidden_els = _hidden_elements(soup)
        dropped = (Comment, Declaration, Doctype, ProcessingInstruction)
        for node in soup.find_all(string=lambda s: isinstance(s, dropped)):
            node.extract()
        for tag in soup.find_all(_DROP_TAGS):
            tag.decompose()

        out.images = (
            sum(1 for tag in soup.find_all(_IMAGE_TAGS) if tag.name != "picture")  # its <img> counts
            + len(soup.find_all(style=_BG_IMAGE))
            + len(soup.find_all("input", attrs={"type": "image"}))
        )
        for tag in soup.find_all([*_IMAGE_TAGS, "map"]):
            if not tag.decomposed:
                tag.decompose()

        hidden = []
        hidden_ids = {id(el) for el in hidden_els}
        for el in hidden_els:
            if not el.decomposed and not any(id(p) in hidden_ids for p in el.parents):
                hidden.append(_text(el))
        for el in hidden_els:
            if not el.decomposed:
                el.decompose()
        out.add(BlockKind.hidden, "숨은 텍스트", "\n".join(hidden))

        out.add_links(
            "링크", (str(a.get("href")) for a in soup.find_all(["a", "area"]) if a.get("href"))
        )

        for kind, name, label in ((BlockKind.header, "header", "머리글"), (BlockKind.footer, "footer", "바닥글")):
            for el in soup.find_all(name):
                if not el.decomposed:
                    out.add(kind, label, _text(el))
                    el.decompose()

        tables = [t for t in soup.find_all("table") if t.find_parent("table") is None]
        root = soup.body or soup
        visible_chars = 0
        for label, kind, text in _sections(root, tables):
            out.add(kind, label, text)
            visible_chars += len("".join(text.split()))

        needs_ocr = visible_chars < self.min_text_chars and out.images > 0
        out.pages.append(PageInfo(1, visible_chars, 0.0, needs_ocr))
        if needs_ocr:
            out.warnings.append("본문 텍스트 없이 그림만 있음, OCR 필요")
        return out.build()


def decode_html(data: bytes) -> str:
    """BOM, then the declared charset (EUC-KR family read as CP949), then UTF-8, then CP949."""
    for bom, codec in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom) :].decode(codec, "replace")
    match = _CHARSET.search(data[:4096])
    if match:
        declared = match.group(1).decode("ascii").lower()
        codec = "cp949" if declared in _KOREAN_LEGACY else declared
        try:
            return data.decode(codec)
        except (LookupError, UnicodeDecodeError):
            pass
    for codec in ("utf-8", "cp949"):
        try:
            return data.decode(codec)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _hidden_elements(soup: BeautifulSoup) -> list[Tag]:
    found: list[Tag] = []

    def add(el: Tag) -> None:
        if all(el is not f for f in found):
            found.append(el)

    for el in soup.find_all(True):
        style = el.get("style") or ""
        if el.has_attr("hidden") or (el.name == "input" and el.get("type") == "hidden"):
            add(el)
        elif style and (_HIDING.search(style) or (_WHITE_TEXT.search(style) and not _BACKGROUND.search(style))):
            add(el)
    for style in soup.find_all("style"):
        for selector, body in _CSS_RULE.findall(style.get_text()):
            if _HIDING.search(body) or (_WHITE_TEXT.search(body) and not _BACKGROUND.search(body)):
                try:
                    for el in soup.select(selector.strip()):
                        add(el)
                except Exception:  # selectors soupsieve cannot handle (:hover, vendor syntax)
                    continue
    return found


def _sections(root: Tag, tables: list[Tag]) -> Iterator[tuple[str, BlockKind, str]]:
    """Body text split around top-level tables, in document order."""
    lines: list[str] = []
    count = 0

    def walk(el: Tag) -> Iterator[tuple[str, BlockKind, str]]:
        nonlocal count
        for child in el.children:
            if isinstance(child, Tag) and any(child is t for t in tables):
                if "".join(lines).strip():
                    yield "본문", BlockKind.body, "".join(lines)
                lines.clear()
                count += 1
                yield f"표 {count}", BlockKind.table, _table(child)
            elif isinstance(child, Tag) and child.find("table") is not None:
                if child.name in _BLOCK_TAGS:
                    lines.append("\n")
                yield from walk(child)
                if child.name in _BLOCK_TAGS:
                    lines.append("\n")
            elif isinstance(child, Tag):
                lines.append(_text(child, outer=True))
            elif isinstance(child, NavigableString):
                lines.append(_squash(str(child)))

    yield from walk(root)
    if "".join(lines).strip():
        yield "본문", BlockKind.body, "".join(lines)


def _table(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = [collapse(_text(td)) for td in tr.find_all(["td", "th"], recursive=False)]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _text(el: Tag, outer: bool = False) -> str:
    """Rendered text: block elements and <br> break lines, inline elements join directly, so
    "김<b>도윤</b>" stays one word."""
    parts: list[str] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(_squash(str(child)))
            elif isinstance(child, Tag):
                if child.name == "br":
                    parts.append("\n")
                elif child.name in _BLOCK_TAGS:
                    parts.append("\n")
                    walk(child)
                    parts.append("\n")
                elif child.name in ("td", "th"):
                    parts.append(" ")
                    walk(child)
                else:
                    walk(child)

    if outer and el.name in _BLOCK_TAGS:
        parts.append("\n")
    if el.name == "br":
        parts.append("\n")
    walk(el)
    if outer and el.name in _BLOCK_TAGS:
        parts.append("\n")
    return "".join(parts)


def _squash(text: str) -> str:
    """HTML whitespace rules: any run of spaces, tabs and newlines renders as one space."""
    return re.sub(r"[ \t\r\n\f]+", " ", text)
