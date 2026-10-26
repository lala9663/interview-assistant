"""HWP (한글) reader: HWP 5.x binary through syhwp, HWPX through our OWPML reader (hwpx.py).

syhwp (MIT, pure Python, pinned 0.0.8) opens the OLE container, checks the password flag,
inflates and, for distribution (배포용) documents, decrypts the BodyText/ViewText sections and
splits them into records. Its own text output mixes headers, footnotes and hidden comments into
the body and has no properties, so the record tree is walked here instead (`_Hwp5Walk`), with
the control ids of the published HWP 5.0 format:

    tbl  table (cells through syhwp's table builder)    head / foot  header / footer
    fn   footnote        en   endnote                     tcmt  hidden comment (숨은 설명)
    %hlk hyperlink field (its command string holds the URL)
    gso  drawing object: text boxes inline, a picture otherwise   eqed  equation script

Properties come from the \\x05HwpSummaryInformation stream (title, subject, author, keywords,
comments, last saved by) and the preview text (PrvText, a copy a viewer does not show) goes to
a hidden block. Pictures are the BinData streams. A password-protected file is refused with
`EncryptedDocument`.

Known gaps (no real 한글-saved sample to check against yet; docs/document-reading.md): white
text in HWP 5.x is not told apart (character shapes live in DocInfo), memos are read as body.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

from interview_assistant.documents.base import (
    BlockCollector,
    DocumentExtractor,
    EncryptedDocument,
    ExtractionError,
    detect_format,
)
from interview_assistant.documents.hwpx import HwpxExtractor, _command_target, read_pictures
from interview_assistant.documents.normalize import collapse
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo, ReadMethod

_SUMMARY = "\x05HwpSummaryInformation"
_SUMMARY_KEYS = {2: "title", 3: "subject", 4: "author", 5: "keywords", 6: "description", 8: "lastmodifiedby"}
_NOTES = {
    "head": (BlockKind.header, "머리글"),
    "foot": (BlockKind.footer, "바닥글"),
    "fn  ": (BlockKind.comment, "각주"),
    "en  ": (BlockKind.comment, "미주"),
    "tcmt": (BlockKind.hidden, "숨은 설명"),
}


class HwpReader(DocumentExtractor):
    """Both 한글 formats behind one admin choice ("HWP·HWPX 읽기")."""

    format = "hwp"

    def __init__(self, *, min_text_chars: int = 30, **_: Any) -> None:
        from interview_assistant.documents.reading import package_version

        self.min_text_chars = min_text_chars
        self.hwpx = HwpxExtractor(min_text_chars=min_text_chars)
        self.tool = f"{package_version('syhwp')} + OWPML 읽기"
        self.model = "syhwp + OWPML"

    async def warm_up(self) -> None:
        import syhwp  # noqa: F401  (ImportError: the requirement check says what to install)

    def extract(self, data: bytes, filename: str, *, reading: Any = None) -> ExtractedDocument:
        if detect_format(data, filename) == "hwpx":
            return self.hwpx.extract(data, filename, reading=reading)
        return self._hwp5(data, filename, reading)

    def _hwp5(self, data: bytes, filename: str, reading: Any) -> ExtractedDocument:
        try:
            from syhwp import _hwp5 as s5
            from syhwp.exceptions import EncryptedDocumentError, SyhwpError
        except ImportError as exc:
            raise ExtractionError("HWP를 읽을 syhwp 패키지가 없습니다 (uv sync).") from exc
        try:
            version, sections = s5._read_hwp5(data)
        except EncryptedDocumentError:
            raise EncryptedDocument(
                "암호가 걸린 HWP 문서입니다. 한글에서 암호를 해제해 다시 저장한 파일을 올려 주세요."
            ) from None
        except SyhwpError as exc:
            raise ExtractionError(f"HWP 파일을 읽을 수 없습니다: {exc}") from None
        except Exception as exc:  # olefile and struct errors on broken files
            raise ExtractionError(f"HWP 파일을 읽을 수 없습니다: {type(exc).__name__}") from None

        out = BlockCollector(filename, self.format)
        streams = _ole_streams(data)
        out.add_metadata(streams.properties)
        walk = _Hwp5Walk(s5)
        for records in sections:
            walk.section(s5._build_tree(records))
        out.add(BlockKind.body, "본문", "\n".join(walk.body))
        for i, table in enumerate(walk.tables, start=1):
            out.add(BlockKind.table, f"표 {i}", table)
        for kind, label, text in walk.notes:
            out.add(kind, label, text)
        out.add(BlockKind.hidden, "미리보기 텍스트", streams.preview)
        out.add_links("링크", walk.links)
        out.images = len(streams.pictures)
        if version:
            out.warnings.append(f"HWP 버전 {version}")

        chars = sum(len("".join(b.text.split())) for b in out.blocks_of(BlockKind.body, BlockKind.table))
        picture_only = chars < self.min_text_chars and bool(streams.pictures)
        if reading is None:
            out.pages.append(
                PageInfo(1, chars, 0.0, picture_only, ReadMethod.held if picture_only else ReadMethod.text)
            )
            if picture_only:
                out.warnings.append("본문 텍스트 없이 그림만 있음, OCR 필요")
            return out.build()
        pictures = [(f"그림 {i}", blob, None) for i, blob in enumerate(streams.pictures, start=1)]
        read_pictures(out, reading, pictures, picture_only=picture_only, chars=chars, tool=self.tool)
        return out.build()


class _Streams:
    def __init__(self) -> None:
        self.properties: list[tuple[str, str]] = []
        self.preview = ""
        self.pictures: list[bytes] = []


def _ole_streams(data: bytes) -> _Streams:
    import olefile

    found = _Streams()
    try:
        ole = olefile.OleFileIO(data)
    except Exception:
        return found
    with ole:
        if ole.exists(_SUMMARY):
            props = summary_strings(ole.openstream(_SUMMARY).read())
            for pid, key in _SUMMARY_KEYS.items():
                if props.get(pid):
                    found.properties.append((key, props[pid]))
        if ole.exists("PrvText"):
            found.preview = ole.openstream("PrvText").read().decode("utf-16-le", "replace").strip("\x00")
            found.preview = found.preview.replace("<", " ").replace(">", " ")
        for entry in ole.listdir(streams=True, storages=False):
            if len(entry) == 2 and entry[0] == "BinData":
                raw = ole.openstream(entry).read()
                found.pictures.append(_maybe_inflate(raw))
    return found


def summary_strings(data: bytes) -> dict[int, str]:
    """String properties of the first section of an OLE property set (MS-OLEPS): property id ->
    text. Parsed here because olefile 0.47 reads UTF-16 strings (VT_LPWSTR) four bytes early."""
    out: dict[int, str] = {}
    try:
        (section,) = struct.unpack_from("<I", data, 44)
        _, count = struct.unpack_from("<II", data, section)
        codepage = 1200
        entries = [struct.unpack_from("<II", data, section + 8 + 8 * i) for i in range(count)]
        for pid, offset in entries:
            if pid == 1:
                (codepage,) = struct.unpack_from("<h", data, section + offset + 4)
                codepage &= 0xFFFF
        for pid, offset in entries:
            vt, n = struct.unpack_from("<II", data, section + offset)
            start = section + offset + 8
            if vt == 0x1F:  # VT_LPWSTR: n characters
                text = data[start : start + 2 * n].decode("utf-16-le", "replace")
            elif vt == 0x1E:  # VT_LPSTR: n bytes in the set's code page
                raw = data[start : start + n]
                encoding = "utf-16-le" if codepage == 1200 else "utf-8" if codepage == 65001 else "cp949"
                text = raw.decode(encoding, "replace")
            else:
                continue
            text = text.split("\x00", 1)[0].strip()
            if text:
                out[pid] = text
    except struct.error:
        return out
    return out


def _maybe_inflate(raw: bytes) -> bytes:
    """BinData streams are raw-deflated when the document is compressed; pictures that already
    start with an image signature are stored as they are."""
    if raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        d = zlib.decompressobj(-15)
        return d.decompress(raw, 64 * 1024 * 1024)
    except zlib.error:
        return raw


class _Hwp5Walk:
    """Labelled text from the record tree of each section (see the module docstring)."""

    def __init__(self, s5: Any) -> None:
        self.s5 = s5
        self.body: list[str] = []
        self.tables: list[str] = []
        self.notes: list[tuple[BlockKind, str, str]] = []
        self.links: list[str] = []
        self.counters: dict[str, int] = {}

    def section(self, root: Any) -> None:
        for node in root.children:
            if node.tag == self.s5.HWPTAG_PARA_HEADER:
                self._paragraph(node, self.body)

    def _paragraph(self, para: Any, sink: list[str]) -> None:
        text = "".join(
            self.s5.decode_para_text(c.payload) for c in para.children if c.tag == self.s5.HWPTAG_PARA_TEXT
        )
        sink.append(text)
        for child in para.children:
            if child.tag == self.s5.HWPTAG_CTRL_HEADER and len(child.payload) >= 4:
                self._control(child, sink)

    def _control(self, ctrl: Any, sink: list[str]) -> None:
        ctrl_id = ctrl.payload[:4][::-1].decode("latin-1")
        if ctrl_id == "tbl ":
            for para in self.s5._caption_paragraphs(ctrl):
                self._paragraph(para, sink)
            table = self.s5._build_table(ctrl)
            if table is not None:
                self.tables.append(_table_text(table))
            return
        if ctrl_id in _NOTES:
            kind, base = _NOTES[ctrl_id]
            lines: list[str] = []
            self._subtree(ctrl, lines)
            text = "\n".join(lines)
            if text.strip():
                self.counters[base] = self.counters.get(base, 0) + 1
                self.notes.append((kind, f"{base} {self.counters[base]}", text))
            return
        if ctrl_id == "%hlk":
            target = _field_command(ctrl.payload)
            if target:
                self.links.append(target)
            return
        if ctrl_id == "eqed":
            script = self.s5._equation_script(ctrl)
            if script:
                sink.append(script)
            return
        self._subtree(ctrl, sink)  # text boxes and anything else that holds paragraphs

    def _subtree(self, node: Any, sink: list[str]) -> None:
        for child in node.children:
            if child.tag == self.s5.HWPTAG_PARA_HEADER:
                self._paragraph(child, sink)
            elif child.tag == self.s5.HWPTAG_CTRL_HEADER and len(child.payload) >= 4:
                self._control(child, sink)
            elif child.tag != self.s5.HWPTAG_TABLE:
                self._subtree(child, sink)


def _table_text(table: Any) -> str:
    rows: dict[int, dict[int, str]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row, {})[cell.col] = collapse(cell.text)
    lines = []
    for r in sorted(rows):
        cells = [rows[r][c] for c in sorted(rows[r])]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _field_command(payload: bytes) -> str:
    """Field CTRL_HEADER: ctrl id (4), property (4), extra property (1), command length (2),
    command (UTF-16). A hyperlink command is "http\\://example.com;1;0;0;"."""
    if len(payload) < 11:
        return ""
    (n,) = struct.unpack_from("<H", payload, 9)
    return _command_target(payload[11 : 11 + 2 * n].decode("utf-16-le", "replace"))

