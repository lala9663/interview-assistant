"""PDF pages as pictures for OCR, with pypdfium2 (Apache-2.0/BSD-3; pdfplumber already needs it).

PDFium is not thread-safe, and uploads are read in worker threads: every call into it goes
through one process-wide lock. A page is rendered once per document and resolution.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

_PDFIUM = threading.Lock()


class PdfRenderer:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self._doc = None
        self._pages: dict[tuple[int, int], Image] = {}

    def page(self, index: int, dpi: int) -> Image:
        key = (index, dpi)
        if key not in self._pages:
            import pypdfium2 as pdfium

            with _PDFIUM:
                if self._doc is None:
                    self._doc = pdfium.PdfDocument(self.data)
                page = self._doc[index]
                try:
                    image = page.render(scale=dpi / 72).to_pil().convert("RGB")
                finally:
                    page.close()
            self._pages = {key: image}  # keep one page: they are large
        return self._pages[key]

    def crop(self, index: int, dpi: int, bbox: tuple[float, float, float, float]) -> Image:
        """A region of the page in PDF points (x0, top, x1, bottom), at `dpi`."""
        scale = dpi / 72
        x0, top, x1, bottom = bbox
        page = self.page(index, dpi)
        box = (
            max(0, round(x0 * scale)),
            max(0, round(top * scale)),
            min(page.width, round(x1 * scale)),
            min(page.height, round(bottom * scale)),
        )
        return page.crop(box)

    def close(self) -> None:
        if self._doc is not None:
            with _PDFIUM:
                self._doc.close()
            self._doc = None
        self._pages.clear()
