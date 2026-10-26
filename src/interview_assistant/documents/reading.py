"""Reading a document: which tool reads each format, and per page, text layer or OCR.

    reader = DocumentReader(policy=ReadingPolicy(), ocr=PaddleOCRProvider(...))
    document = reader.read(upload_bytes, upload_filename)   # in a worker thread

Per page (PDF page, slide, image file; a DOCX/HWP/HTML file is one page):
- auto (default): the text layer when there is one and it is not garbled (quality.py); OCR when
  there is none (a scan, a picture-only page) or when it is garbled. The garbled text is dropped:
  it is never sent, not even as hidden text, because the de-identifier cannot read it.
- always_ocr: every PDF page and image is read by OCR. Text that only a file reader sees (hidden
  text, properties, links, notes) is still extracted and de-identified.
- text_only: no OCR. Pages without a usable text layer are held (`needs_ocr`), as before OCR.

Pictures inside a document (a certificate photo in a DOCX, a captured slide) are read by OCR when
`embedded_images` is on, into `image_text` blocks. A picture that looks like an ID photo
(images.check_picture) is dropped without being read, whatever the setting.

Every page records how it was read (method, reason, tool and version, OCR confidence, time),
every picture what was done with it, and the document the settings and tools (`ReadingRecord`).
Pictures and pages are rendered and read on this machine or by the configured OCR provider; no
image is ever sent to an LLM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from interview_assistant.documents import ocrfix
from interview_assistant.documents.base import (
    DocumentExtractor,
    ExtractionError,
    UnsupportedFormat,
    detect_format,
)
from interview_assistant.documents.images import check_picture
from interview_assistant.documents.quality import SENSITIVITY, TextQuality
from interview_assistant.documents.types import ExtractedDocument, ImageInfo, ReadingRecord, ReadMethod

if TYPE_CHECKING:
    from PIL.Image import Image

    from interview_assistant.providers.base import OcrResult

MODES = ("auto", "always_ocr", "text_only")
MODE_LABELS = {"auto": "자동", "always_ocr": "항상 OCR", "text_only": "텍스트만"}


@dataclass(frozen=True)
class ReadingPolicy:
    mode: str = "auto"
    embedded_images: bool = True
    sensitivity: str = "medium"
    dpi: int = 200  # PDF pages are rendered at this resolution for OCR
    low_confidence: float = 0.80  # OCR pages below this mean confidence get a warning

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown reading mode '{self.mode}' (known: {', '.join(MODES)})")
        if self.sensitivity not in SENSITIVITY:
            raise ValueError(f"unknown sensitivity '{self.sensitivity}'")


class ReadingPolicyProvider:
    """The "읽기 방식" setting as a provider, so the admin screen picks, tests, applies and rolls
    it back like the AI models (ai_models/)."""

    model = "읽기 방식"

    def __init__(
        self,
        mode: str = "auto",
        embedded_images: bool = True,
        sensitivity: str = "medium",
        dpi: int = 200,
        low_confidence: float = 0.8,
        **_: Any,
    ) -> None:
        self.policy = ReadingPolicy(mode, embedded_images, sensitivity, dpi, low_confidence)
        self.model = f"{MODE_LABELS[mode]} · 그림 OCR {'켬' if embedded_images else '끔'} · 깨짐 판정 {sensitivity}"

    async def warm_up(self) -> None:
        return None


@dataclass
class PageReader:
    """What an extractor asks while it reads: should this page be OCR'd, read it, read this picture.

    Holds the outcome of every OCR call for the reading record. OCR problems (engine missing,
    model files not downloaded, a crash) never raise: the page is held instead, with the reason.
    """

    policy: ReadingPolicy
    ocr: Any = None  # OCRProvider, or None when no engine is configured
    tools: list[str] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problem: str = ""  # why the last OCR call read nothing

    # --- decisions --------------------------------------------------------------------------

    def plan(
        self, *, has_text: bool, quality: TextQuality | None = None, renderable: bool = True
    ) -> tuple[ReadMethod, str]:
        """How to read a page: `has_text` = a usable text layer exists; `quality` = its check;
        `renderable` = the page can be turned into an image (PDF page, image file, picture-only
        page). Returns (method, reason)."""
        garbled = quality is not None and quality.garbled(self.policy.sensitivity)
        if self.policy.mode == "always_ocr" and renderable:
            return ReadMethod.ocr, "항상 OCR 설정"
        if has_text and not garbled:
            return ReadMethod.text, ""
        reason = (
            f"텍스트 층이 깨짐 ({quality.describe()})" if garbled and quality else "텍스트 층 없음"
        )
        if self.policy.mode == "text_only":
            return ReadMethod.held, f"{reason}, 텍스트만 읽기 설정이라 보류"
        if not renderable:
            return ReadMethod.held, f"{reason}, 그림으로 바꿀 수 없어 보류"
        return ReadMethod.ocr, reason

    @property
    def reads_pictures(self) -> bool:
        return self.policy.embedded_images and self.policy.mode != "text_only"

    # --- OCR --------------------------------------------------------------------------------

    def read(self, image: Image) -> tuple[OcrResult | None, str]:
        """OCR one page image. (result, "") or (None, why it could not be read)."""
        if self.ocr is None:
            self.problem = "OCR 엔진이 설정되지 않음"
            return None, self.problem
        try:
            result = self.ocr.recognize(image)
        except Exception as exc:  # engine missing, weights deleted, crash: hold, don't fail
            reason = str(exc).strip() or type(exc).__name__
            self.problem = f"OCR 실패: {reason}"
            return None, self.problem
        self.note_tool(getattr(self.ocr, "version", "") or result.model)
        lines = tuple(replace(line, text=ocrfix.correct(line.text)) for line in result.lines)
        return replace(result, lines=lines), ""

    def picture(
        self, image: Image, label: str, *, share: float | None = None, force: bool = False
    ) -> OcrResult | None:
        """A picture inside a document. ID photos are dropped unread; others are OCR'd when the
        setting allows (`force`: the picture is the page, e.g. a scan pasted into Word)."""
        width, height = image.size
        check = check_picture(image, share=share)
        if check.kind == "photo" and not force:
            self.images.append(ImageInfo(label, width, height, "photo", detail=check.detail))
            return None
        if check.kind == "small" and not force:
            self.images.append(ImageInfo(label, width, height, "small", detail=check.detail))
            return None
        if not (force or self.reads_pictures):
            reason = "텍스트만 읽기 설정" if self.policy.mode == "text_only" else "문서 속 그림 OCR 꺼짐"
            self.images.append(ImageInfo(label, width, height, "skipped", detail=reason))
            return None
        result, problem = self.read(image)
        if result is None:
            self.images.append(ImageInfo(label, width, height, "failed", detail=problem))
            self.warnings.append(f"{label}: {problem}")
            return None
        self.images.append(
            ImageInfo(label, width, height, "ocr", result.confidence, result.elapsed_ms, check.detail)
        )
        return result

    def note_tool(self, tool: str) -> None:
        if tool and tool not in self.tools:
            self.tools.append(tool)

    def check_confidence(self, label: str, result: OcrResult) -> None:
        confidence = result.confidence
        if confidence is not None and confidence < self.policy.low_confidence:
            self.warnings.append(
                f"{label}: OCR 신뢰도 {confidence:.0%} (기준 {self.policy.low_confidence:.0%} 미만), 사람이 확인 필요"
            )


def package_version(name: str) -> str:
    try:
        return f"{name} {version(name)}"
    except PackageNotFoundError:
        return name


class DocumentReader:
    """Picks the extractor for a file's format and reads it with one `PageReader`.

    `extractors` maps a format to its reader (the admin settings choose the PDF and HWP readers);
    `converter` turns legacy .doc/.ppt into .docx/.pptx first (LibreOffice). `revision` is the
    model-settings revision the reading runs under, recorded with the result.
    """

    def __init__(
        self,
        *,
        policy: ReadingPolicy | None = None,
        ocr: Any = None,
        extractors: dict[str, DocumentExtractor] | None = None,
        converter: Any = None,
        revision: int | None = None,
    ) -> None:
        from interview_assistant.documents.base import default_extractors

        self.policy = policy or ReadingPolicy()
        self.ocr = ocr
        self.extractors = {**default_extractors(), **(extractors or {})}
        self.converter = converter
        self.revision = revision

    def read(self, data: bytes, filename: str) -> ExtractedDocument:
        started = time.perf_counter()
        fmt = detect_format(data, filename)
        pages = PageReader(self.policy, self.ocr)
        converted_from = None
        if fmt in ("doc", "ppt"):
            if self.converter is None:
                from interview_assistant.documents.base import ConverterMissing

                raise ConverterMissing(f"구형 .{fmt} 파일을 바꿀 변환기가 설정되지 않았습니다.")
            data = self.converter.convert(data, fmt)
            pages.note_tool(getattr(self.converter, "version", "") or "converter")
            converted_from, fmt = fmt, {"doc": "docx", "ppt": "pptx"}[fmt]
        extractor = self.extractors.get(fmt)
        if extractor is None:
            raise UnsupportedFormat(f"'{fmt}' 형식의 읽기 도구가 설정되지 않았습니다.")
        document = extractor.extract(data, filename, reading=pages)
        tools = [getattr(extractor, "tool", "") or type(extractor).__name__, *pages.tools]
        record = ReadingRecord(
            mode=self.policy.mode,
            embedded_images=self.policy.embedded_images,
            sensitivity=self.policy.sensitivity,
            tools=tuple(dict.fromkeys(t for t in tools if t)),
            revision=self.revision,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            converted_from=converted_from,
        )
        return replace(
            document,
            format=converted_from or document.format,
            images=(*document.images, *pages.images),
            warnings=(*document.warnings, *pages.warnings),
            reading=record,
        )


__all__ = [
    "MODES",
    "DocumentReader",
    "ExtractionError",
    "PageReader",
    "ReadingPolicy",
    "ReadingPolicyProvider",
    "package_version",
]
