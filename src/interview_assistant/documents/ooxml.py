"""Shared by the DOCX and PPTX extractors: document properties and image counting.

Properties are read straight from the package (docProps/core.xml, app.xml, custom.xml) rather
than through python-docx / python-pptx, because those only expose core.xml. app.xml holds
Company, Manager and Template, and custom.xml any user-defined property; all three can carry a
name.
"""

from __future__ import annotations

import io
import posixpath
import zipfile

from lxml import etree

# Untrusted XML: no entity expansion, no DTD fetching, no network.
XML_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, recover=True
)

_IMAGE_EXTENSIONS = frozenset(
    ".png .jpg .jpeg .jpe .gif .bmp .tif .tiff .emf .wmf .svg .webp .ico .jfif .heic".split()
)
_APP_FIELDS = ("Company", "Manager", "Template", "HyperlinkBase", "Application")


def parse_xml(data: bytes) -> etree._Element | None:
    try:
        return etree.fromstring(data, XML_PARSER)
    except etree.XMLSyntaxError:
        return None


def local(tag: object) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def read_properties(data: bytes) -> list[tuple[str, str]]:
    """(key, value) pairs from core, app and custom properties, in that order."""
    out: list[tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())

        def load(name: str) -> etree._Element | None:
            return parse_xml(zf.read(name)) if name in names else None

        if (core := load("docProps/core.xml")) is not None:
            for el in core:
                if el.text and el.text.strip():
                    out.append((local(el.tag), el.text))
        if (app := load("docProps/app.xml")) is not None:
            for el in app:
                if local(el.tag) in _APP_FIELDS and el.text and el.text.strip():
                    out.append((local(el.tag), el.text))
        if (custom := load("docProps/custom.xml")) is not None:
            for prop in custom:
                value = "".join(prop.itertext()).strip()
                if value:
                    out.append((prop.get("name") or "custom", value))
    return out


def count_images(data: bytes, prefix: str = "") -> int:
    """Image files in the package (under `prefix`): photos, logos, the docProps thumbnail."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return sum(
            1
            for name in zf.namelist()
            if name.startswith(prefix) and posixpath.splitext(name)[1].lower() in _IMAGE_EXTENSIONS
        )
