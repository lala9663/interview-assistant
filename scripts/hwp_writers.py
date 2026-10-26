"""Writers for synthetic 한글 files, used by make_resume_fixtures.py. Test data only.

HWPX (OWPML) is a zip of XML parts; the writer emits the parts a reader needs (content.hpf with
properties, header.xml with character styles, section0.xml, the preview text, BinData pictures).

HWP 5.0 is an OLE compound file of record streams. `write_cfb` is a minimal compound file writer
(version 3, 512-byte sectors, no mini stream: every stream is padded to the 4096-byte cutoff, which
readers accept); `Hwp5` builds FileHeader, DocInfo, BodyText/Section0 (raw-deflated records),
\\x05HwpSummaryInformation, PrvText and BinData from the published HWP 5.0 format. These files were
never opened in 한글: they exercise our reader's paths, they do not prove it reads real 한글 output
(docs/document-reading.md asks for real samples saved from 한컴오피스).
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime

# --- OLE compound file -------------------------------------------------------------------------

_SECTOR = 512
_FREE, _END, _FAT, _NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
_MINI_CUTOFF = 4096


def write_cfb(streams: dict[str, bytes]) -> bytes:
    """`streams`: path ("BodyText/Section0") -> bytes. Storages are created from the paths."""
    data = {path: blob + b"\0" * max(0, _MINI_CUTOFF - len(blob)) for path, blob in streams.items()}

    # Directory: root, then storages and streams in path order.
    entries: list[dict] = [{"name": "Root Entry", "type": 5, "children": []}]
    index: dict[str, int] = {"": 0}
    for path in sorted(data, key=lambda p: (p.count("/"), p)):
        parts = path.split("/")
        for depth in range(1, len(parts)):
            storage = "/".join(parts[:depth])
            if storage not in index:
                index[storage] = len(entries)
                entries.append({"name": parts[depth - 1], "type": 1, "children": []})
                entries[index["/".join(parts[: depth - 1])]]["children"].append(index[storage])
        index[path] = len(entries)
        entries.append({"name": parts[-1], "type": 2, "children": [], "path": path})
        entries[index["/".join(parts[:-1])]]["children"].append(index[path])

    # Stream sectors first.
    fat: list[int] = []
    body = bytearray()
    for entry in entries:
        if entry["type"] != 2:
            continue
        blob = data[entry["path"]]
        count = -(-len(blob) // _SECTOR)
        start = len(fat)
        entry["start"], entry["size"] = start, len(blob)
        fat.extend(range(start + 1, start + count))
        fat.append(_END)
        body += blob + b"\0" * (count * _SECTOR - len(blob))

    # Directory sectors.
    dir_bytes = b"".join(_dir_entry(entries, i) for i in range(len(entries)))
    dir_bytes += _empty_entry() * ((-len(entries)) % 4)
    dir_count = len(dir_bytes) // _SECTOR
    dir_start = len(fat)
    fat.extend(range(dir_start + 1, dir_start + dir_count))
    fat.append(_END)
    body += dir_bytes

    # FAT sectors (they describe themselves too).
    fat_count = 1
    while (len(fat) + fat_count) > fat_count * (_SECTOR // 4):
        fat_count += 1
    fat_start = len(fat)
    fat.extend([_FAT] * fat_count)
    fat.extend([_FREE] * (fat_count * (_SECTOR // 4) - len(fat)))
    body += struct.pack(f"<{len(fat)}I", *fat)

    difat = list(range(fat_start, fat_start + fat_count)) + [_FREE] * (109 - fat_count)
    header = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
        + struct.pack("<IIIIIIIII", 0, fat_count, dir_start, 0, _MINI_CUTOFF, _END, 0, _END, 0)
        + struct.pack("<109I", *difat)
    )  # fmt: skip
    return header + bytes(body)


def _dir_entry(entries: list[dict], i: int) -> bytes:
    entry = entries[i]
    name = entry["name"].encode("utf-16-le") + b"\0\0"
    # Children of every storage: a chain through the right siblings, ordered as the format sorts
    # names (shorter first, then case-insensitive). Every node black; readers do not rebalance.
    right = _NOSTREAM
    for siblings in (e["children"] for e in entries):
        ordered = sorted(siblings, key=lambda k: (len(entries[k]["name"]), entries[k]["name"].upper()))
        if i in ordered and ordered.index(i) + 1 < len(ordered):
            right = ordered[ordered.index(i) + 1]
    children = sorted(entry["children"], key=lambda k: (len(entries[k]["name"]), entries[k]["name"].upper()))
    child = children[0] if children else _NOSTREAM
    start = entry.get("start", _END if entry["type"] == 5 else 0)
    return (
        name + b"\0" * (64 - len(name))
        + struct.pack("<HBB", len(name), entry["type"], 1)
        + struct.pack("<III", _NOSTREAM, right, child)
        + b"\0" * 16 + b"\0" * 4 + b"\0" * 16
        + struct.pack("<IQ", start, entry.get("size", 0))
    )  # fmt: skip


def _empty_entry() -> bytes:
    return b"\0" * 64 + struct.pack("<HBB", 0, 0, 0) + struct.pack("<III", _NOSTREAM, _NOSTREAM, _NOSTREAM) + b"\0" * 48


# --- HWP 5.0 ------------------------------------------------------------------------------------

_PARA_HEADER, _PARA_TEXT, _CTRL_HEADER, _LIST_HEADER, _TABLE = 66, 67, 71, 72, 77
_SUMMARY_FMTID = bytes.fromhex("E0859FF2F94F6810AB9108002B27B3D9")


def _record(tag: int, level: int, payload: bytes) -> bytes:
    if len(payload) < 0xFFF:
        return struct.pack("<I", tag | (level << 10) | (len(payload) << 20)) + payload
    return struct.pack("<II", tag | (level << 10) | (0xFFF << 20), len(payload)) + payload


def _control_char(code: int, ctrl_id: str) -> str:
    """An extended control occupies 8 UTF-16 units: code, the control id, padding, code."""
    raw = ctrl_id.encode("ascii")[::-1]
    lo, hi = struct.unpack("<HH", raw)
    return "".join(map(chr, (code, lo, hi, 0, 0, 0, 0, code)))


@dataclass
class Hwp5:
    """A one-section document. Each body item is a paragraph: plain text, or text with controls."""

    title: str = ""
    author: str = ""
    last_author: str = ""
    subject: str = ""
    keywords: str = ""
    comments: str = ""
    preview: str = ""
    password: bool = False
    pictures: list[bytes] = field(default_factory=list)
    _body: list[bytes] = field(default_factory=list)

    # paragraphs -------------------------------------------------------------------------------

    def paragraph(self, text: str, *, header: str = "", footer: str = "", footnote: str = "",
                  hidden: str = "", link: tuple[str, str] | None = None) -> None:  # fmt: skip
        """Text plus, anchored in it, a header, footer, footnote or hidden comment (숨은 설명), or a
        hyperlink (target, label) around its end."""
        prefix, controls = "", []
        for code, ctrl_id, content in ((16, "head", header), (16, "foot", footer), (17, "fn  ", footnote), (15, "tcmt", hidden)):
            if content:
                prefix += _control_char(code, ctrl_id)
                controls.append(self._list_control(ctrl_id, [content], level=1))
        suffix = ""
        if link is not None:
            target, label = link
            suffix = _control_char(3, "%hlk") + label + _control_char(4, "%hlk")
            command = target.replace(":", "\\:") + ";1;0;0;"
            payload = b"klh%" + struct.pack("<IB", 0, 0) + struct.pack("<H", len(command)) + command.encode("utf-16-le") + struct.pack("<I", 1)
            controls.append(_record(_CTRL_HEADER, 1, payload))
        self._body.append(self._para(prefix + text + suffix, 0, b"".join(controls)))

    def table(self, rows: list[list[str]], caption_before: str = "") -> None:
        text = _control_char(11, "tbl ")
        level = 1
        records = _record(_CTRL_HEADER, level, b" lbt" + struct.pack("<I", 0))
        n_rows, n_cols = len(rows), max(len(r) for r in rows)
        records += _record(_TABLE, level + 1, struct.pack("<IHH", 0, n_rows, n_cols) + b"\0" * 10)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                header = struct.pack("<HIH", 1, 0, 0) + struct.pack("<HHHH", c, r, 1, 1) + b"\0" * 16
                records += _record(_LIST_HEADER, level + 1, header)
                records += self._para(value, level + 1, b"")
        if caption_before:
            self.paragraph(caption_before)
        self._body.append(self._para(text, 0, records))

    def text_box(self, lines: list[str]) -> None:
        text = _control_char(11, "gso ")
        records = _record(_CTRL_HEADER, 1, b" osg" + struct.pack("<I", 0))
        records += _record(_LIST_HEADER, 2, struct.pack("<HI", len(lines), 0) + b"\0" * 10)
        for line in lines:
            records += self._para(line, 2, b"")
        self._body.append(self._para(text, 0, records))

    def _list_control(self, ctrl_id: str, paragraphs: list[str], *, level: int) -> bytes:
        records = _record(_CTRL_HEADER, level, ctrl_id.encode("ascii")[::-1] + struct.pack("<I", 0))
        records += _record(_LIST_HEADER, level + 1, struct.pack("<HI", len(paragraphs), 0) + b"\0" * 10)
        for text in paragraphs:
            records += self._para(text, level + 1, b"")
        return records

    @staticmethod
    def _para(text: str, level: int, controls: bytes) -> bytes:
        units = text + "\r"
        header = struct.pack("<IIHBBHHHIH", len(units), 0, 0, 0, 0, 1, 0, 1, 0, 0)
        return (
            _record(_PARA_HEADER, level, header)
            + _record(_PARA_TEXT, level + 1, units.encode("utf-16-le"))
            + controls
        )

    # file -------------------------------------------------------------------------------------

    def build(self) -> bytes:
        flags = 0x01 | (0x02 if self.password else 0)
        file_header = b"HWP Document File".ljust(32, b"\0") + struct.pack("<II", 0x05010101, flags)
        file_header = file_header.ljust(256, b"\0")
        section = b"".join(self._body)
        streams = {
            "FileHeader": file_header,
            "DocInfo": _deflate(_record(16, 0, struct.pack("<HHHHHHHI", 1, 1, 1, 1, 1, 1, 1, 0))),
            "BodyText/Section0": _deflate(section),
            "\x05HwpSummaryInformation": self._summary(),
            "PrvText": self.preview.encode("utf-16-le"),
        }
        for i, picture in enumerate(self.pictures, start=1):
            streams[f"BinData/BIN{i:04X}.png"] = _deflate(picture)
        return write_cfb(streams)

    def _summary(self) -> bytes:
        """An OLE property set (MS-OLEPS) with UTF-16 strings, as 한글 writes its summary."""
        values = [(2, self.title), (3, self.subject), (4, self.author), (5, self.keywords), (6, self.comments), (8, self.last_author)]
        values = [(pid, v) for pid, v in values if v]
        props = [(1, struct.pack("<Ih", 2, 1200) + b"\0\0")]  # codepage: UTF-16
        for pid, value in values:
            raw = (value + "\0").encode("utf-16-le")
            raw += b"\0" * ((-len(raw)) % 4)
            props.append((pid, struct.pack("<II", 0x1F, len(value) + 1) + raw))
        offset = 8 + 8 * len(props)
        table, blobs = b"", b""
        for pid, blob in props:
            table += struct.pack("<II", pid, offset + len(blobs))
            blobs += blob
        section = struct.pack("<II", 8 + len(table) + len(blobs), len(props)) + table + blobs
        header = struct.pack("<HHI", 0xFFFE, 0, 0x00020006) + b"\0" * 16 + struct.pack("<I", 1)
        return header + _SUMMARY_FMTID + struct.pack("<I", 48) + section


def _deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


# --- HWPX ---------------------------------------------------------------------------------------

_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"'
)


def _x(text: str) -> str:
    from xml.sax.saxutils import escape

    return escape(text)


@dataclass
class Hwpx:
    """Paragraph XML is collected in order; `build` wraps it into a package."""

    title: str = ""
    creator: str = ""
    last_saved_by: str = ""
    subject: str = ""
    description: str = ""
    keywords: str = ""
    preview: str = ""
    track_authors: list[str] = field(default_factory=list)
    pictures: list[tuple[str, bytes]] = field(default_factory=list)  # (item id, png bytes)
    created: datetime = datetime(2026, 10, 1, 9, 0, 0)
    _paras: list[str] = field(default_factory=list)
    _ids: int = 0

    def _id(self) -> int:
        self._ids += 1
        return self._ids

    @staticmethod
    def run(text: str, char: int = 0) -> str:
        return f'<hp:run charPrIDRef="{char}"><hp:t>{_x(text)}</hp:t></hp:run>'

    def _p(self, inner: str) -> str:
        return f'<hp:p id="{self._id()}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{inner}</hp:p>'

    def _sublist(self, lines: list[str]) -> str:
        paras = "".join(self._p(self.run(line)) for line in lines)
        return f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP">{paras}</hp:subList>'

    def first(self, *, header: str = "", footer: str = "") -> None:
        """The section's first paragraph: page size, then the header and footer controls."""
        ctrls = ""
        if header:
            ctrls += f'<hp:ctrl><hp:header id="{self._id()}" applyPageType="BOTH">{self._sublist([header])}</hp:header></hp:ctrl>'
        if footer:
            ctrls += f'<hp:ctrl><hp:footer id="{self._id()}" applyPageType="BOTH">{self._sublist([footer])}</hp:footer></hp:ctrl>'
        sec = '<hp:secPr id="" textDirection="HORIZONTAL"><hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY"/></hp:secPr>'
        self._paras.append(self._p(f'<hp:run charPrIDRef="0">{sec}{ctrls}<hp:t/></hp:run>'))

    def paragraph(self, text: str, *, white: str = "", footnote: str = "", hidden: str = "",
                  link: tuple[str, str] | None = None) -> None:  # fmt: skip
        inner = self.run(text)
        if white:
            inner += self.run(" " + white, char=1)
        if footnote:
            inner += f'<hp:run charPrIDRef="0"><hp:ctrl><hp:footNote number="1" instId="{self._id()}">{self._sublist([footnote])}</hp:footNote></hp:ctrl></hp:run>'
        if hidden:
            inner += f'<hp:run charPrIDRef="0"><hp:ctrl><hp:hiddenComment>{self._sublist([hidden])}</hp:hiddenComment></hp:ctrl></hp:run>'
        if link is not None:
            target, label = link
            command = target.replace(":", "\\:") + ";1;0;0;"
            begin = (
                f'<hp:fieldBegin id="{self._id()}" type="HYPERLINK" name="" editable="0" dirty="0" zorder="-1" fieldid="{self._id()}">'
                f'<hp:parameters cnt="4" name=""><hp:integerParam name="Prop">0</hp:integerParam>'
                f'<hp:stringParam name="Command">{_x(command)}</hp:stringParam>'
                f'<hp:stringParam name="Path">{_x(target)}</hp:stringParam>'
                f'<hp:stringParam name="Category">HWPHYPERLINK_TYPE_URL</hp:stringParam></hp:parameters></hp:fieldBegin>'
            )
            inner += f'<hp:run charPrIDRef="0"><hp:ctrl>{begin}</hp:ctrl><hp:t>{_x(label)}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="{self._ids}" fieldid="{self._ids}"/></hp:ctrl></hp:run>'
        self._paras.append(self._p(inner))

    def table(self, rows: list[list[str]], caption: str = "") -> None:
        trs = ""
        for r, row in enumerate(rows):
            tds = "".join(
                f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="1">'
                f"{self._sublist(value.split(chr(10)))}"
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="8000" height="1800"/></hp:tc>'
                for c, value in enumerate(row)
            )
            trs += f"<hp:tr>{tds}</hp:tr>"
        cap = f'<hp:caption side="TOP">{self._sublist([caption])}</hp:caption>' if caption else ""
        tbl = f'<hp:tbl id="{self._id()}" rowCnt="{len(rows)}" colCnt="{max(len(r) for r in rows)}" cellSpacing="0" borderFillIDRef="1">{cap}{trs}</hp:tbl>'
        self._paras.append(self._p(f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run>'))

    def picture(self, item: str, width: int, height: int) -> None:
        """A picture placed in its own paragraph; size in HWPUNIT (1/7200 inch)."""
        pic = (
            f'<hp:pic id="{self._id()}" zOrder="0" numberingType="PICTURE" textWrap="SQUARE">'
            f'<hp:orgSz width="{width}" height="{height}"/><hp:curSz width="{width}" height="{height}"/>'
            f'<hc:img binaryItemIDRef="{item}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/></hp:pic>'
        )
        self._paras.append(self._p(f'<hp:run charPrIDRef="0">{pic}<hp:t/></hp:run>'))

    def text_box(self, lines: list[str]) -> None:
        box = (
            f'<hp:rect id="{self._id()}" zOrder="1" numberingType="FIGURE" textWrap="IN_FRONT_OF_TEXT">'
            f'<hp:drawText lastWidth="20000" name="" editable="0">{self._sublist(lines)}</hp:drawText>'
            f'<hp:sz width="20000" widthRelTo="ABSOLUTE" height="6000" heightRelTo="ABSOLUTE" protect="0"/></hp:rect>'
        )
        self._paras.append(self._p(f'<hp:run charPrIDRef="0">{box}<hp:t/></hp:run>'))

    def build(self, thumbnail: bytes) -> bytes:
        stamp = self.created.strftime("%Y-%m-%dT%H:%M:%SZ")
        items = "".join(
            f'<opf:item id="{item}" href="BinData/{item}.png" media-type="image/png" isEmbeded="1"/>'
            for item, _ in self.pictures
        )
        meta = "".join(
            f'<opf:meta name="{name}" content="text">{_x(value)}</opf:meta>' if value else f'<opf:meta name="{name}" content="text"/>'
            for name, value in (
                ("creator", self.creator), ("subject", self.subject), ("description", self.description),
                ("lastsaveby", self.last_saved_by), ("CreatedDate", stamp), ("ModifiedDate", stamp),
                ("date", "2026년 10월 1일 목요일 오전 9:00:00"), ("keyword", self.keywords),
            )
        )  # fmt: skip
        content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:dc="http://purl.org/dc/elements/1.1/" version="" unique-identifier="" id="">'
            f"<opf:metadata><opf:title>{_x(self.title)}</opf:title><opf:language>ko</opf:language>{meta}</opf:metadata>"
            '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            f'<opf:item id="settings" href="settings.xml" media-type="application/xml"/>{items}</opf:manifest>'
            '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>'
            "</opf:package>"
        )
        authors = "".join(f'<hh:trackChangeAuthor id="{i}" name="{_x(n)}" mark="0" color="#0000FF"/>' for i, n in enumerate(self.track_authors))
        header = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<hh:head {_NS} version="1.5" secCnt="1"><hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
            '<hh:refList><hh:charProperties itemCnt="2">'
            '<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1"/>'
            '<hh:charPr id="1" height="400" textColor="#FFFFFF" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1"/>'
            "</hh:charProperties></hh:refList>"
            + (f'<hh:trackChangeAuthors itemCnt="{len(self.track_authors)}">{authors}</hh:trackChangeAuthors>' if authors else "")
            + "</hh:head>"
        )
        section = f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {_NS}>{"".join(self._paras)}</hs:sec>'
        version = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
            'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" '
            'application="Hancom Office Hangul" appVersion="12, 0, 0, 0 WIN32LEWindows_10"/>'
        )
        container = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
            'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
            'media-type="application/hwpml-package+xml"/><ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
            "</ocf:rootfiles></ocf:container>"
        )
        files = {
            "version.xml": version,
            "META-INF/container.xml": container,
            "META-INF/manifest.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>',
            "Contents/content.hpf": content,
            "Contents/header.xml": header,
            "Contents/section0.xml": section,
            "settings.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"/>',
            "Preview/PrvText.txt": self.preview,
        }
        out = io.BytesIO()
        fixed = self.created.timetuple()[:6]
        with zipfile.ZipFile(out, "w") as zf:
            info = zipfile.ZipInfo("mimetype", date_time=fixed)
            zf.writestr(info, "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
            for name, text in files.items():
                info = zipfile.ZipInfo(name, date_time=fixed)
                zf.writestr(info, text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            for item, blob in self.pictures:
                zf.writestr(zipfile.ZipInfo(f"BinData/{item}.png", date_time=fixed), blob, compress_type=zipfile.ZIP_STORED)
            zf.writestr(zipfile.ZipInfo("Preview/PrvImage.png", date_time=fixed), thumbnail, compress_type=zipfile.ZIP_STORED)
        return out.getvalue()
