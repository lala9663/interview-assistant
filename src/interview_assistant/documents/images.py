"""Pictures in the raw zone: opening image files, their embedded text metadata, and telling an ID
photo from a picture that carries text.

Nothing here keeps or forwards a picture. OCR reads text out of it (documents/reading.py) and the
picture is dropped; an ID photo is dropped without being read at all.

ID photo (증명사진) test, without OCR and without face detection: portrait 3:4-ish, small on its
page when the placement is known, and not text-like. A picture of text (a certificate, a
captured slide, a scan) is mostly one background tone with a little ink far from it (dark text
on paper, light text on a dark slide) and few tones in between; a photo, even one shot against a
plain studio wall, is full of in-between tones (face, hair, clothes). Measured on a grey copy at
most 320 px long: background = within 24 of the most common tone, ink = more than 80 away,
middle = the rest. Text-like: background at least 70%, ink at least 0.3%, middle at most 20%.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

MIN_PIXELS = 160 * 160  # below this a picture is an icon or a logo: nothing worth reading
PHOTO_ASPECT = (0.62, 0.92)  # width / height of a portrait ID photo (3:4 is 0.75)
PHOTO_MAX_SHARE = 0.10  # an ID photo covers at most this much of its page
PHOTO_MAX_PIXELS = 1_600_000  # placement unknown: an ID photo is not a 12 MP camera shot
TEXT_MIN_BACKGROUND = 0.70
TEXT_MIN_INK = 0.003
TEXT_MAX_MIDDLE = 0.20

# EXIF tags that hold free text a person typed (author, description, comment, copyright).
_EXIF_TEXT = {
    0x010E: "ImageDescription",
    0x013B: "Artist",
    0x8298: "Copyright",
    0x9C9B: "XPTitle",
    0x9C9C: "XPComment",
    0x9C9D: "XPAuthor",
    0x9C9E: "XPKeywords",
    0x9C9F: "XPSubject",
    0x9286: "UserComment",
    0xA430: "CameraOwnerName",
    0xA431: "BodySerialNumber",
}
_EXIF_LABELS = {
    "ImageDescription": "설명",
    "Artist": "작성자",
    "XPAuthor": "작성자",
    "Copyright": "저작권",
    "XPTitle": "제목",
    "XPComment": "설명",
    "UserComment": "설명",
    "XPKeywords": "키워드",
    "XPSubject": "주제",
    "CameraOwnerName": "카메라 소유자",
    "BodySerialNumber": "카메라 일련번호",
}


class ImageError(ValueError):
    pass


def open_image(data: bytes) -> Image:
    """The picture upright (EXIF orientation applied), fully loaded, in RGB or L."""
    from PIL import Image as PILImage
    from PIL import ImageOps, UnidentifiedImageError

    try:
        image = PILImage.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError) as exc:
        raise ImageError(f"그림을 열 수 없습니다: {exc}") from None
    image = ImageOps.exif_transpose(image) or image
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGBA").convert("RGB") if "A" in image.mode else image.convert("RGB")
    return image


def text_metadata(data: bytes) -> list[tuple[str, str]]:
    """(label, value) pairs from EXIF text tags and PNG text chunks: a phone or an editor can put
    the owner's name there. GPS and camera settings are not text and are not read."""
    from PIL import Image as PILImage

    out: list[tuple[str, str]] = []
    try:
        image = PILImage.open(io.BytesIO(data))
    except Exception:
        return out
    try:
        exif = image.getexif()
        tags = dict(exif)
        tags.update(exif.get_ifd(0x8769))  # Exif sub-IFD: UserComment, camera owner
    except Exception:
        tags = {}
    for tag, name in _EXIF_TEXT.items():
        value = _exif_text(tags.get(tag))
        if value:
            out.append((_EXIF_LABELS[name], value))
    for key, value in (getattr(image, "text", None) or {}).items():  # PNG tEXt / iTXt
        if isinstance(value, str) and value.strip():
            out.append(("기타 속성", f"{key}: {value.strip()}"))
    return out


def _exif_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        if value[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"JIS\x00\x00\x00\x00\x00"):
            head, value = value[:8], value[8:]
            encoding = "utf-16-be" if head.startswith(b"UNICODE") else "utf-8"
            return value.decode(encoding, "replace").strip("\x00 ").strip()
        try:
            return value.decode("utf-16-le").strip("\x00 ").strip()  # XP* tags
        except UnicodeDecodeError:
            return value.decode("utf-8", "replace").strip("\x00 ").strip()
    if isinstance(value, tuple) and all(isinstance(v, int) for v in value):  # XP* as ints
        return bytes(value).decode("utf-16-le", "replace").strip("\x00 ").strip()
    return str(value).strip("\x00 ").strip()


@dataclass(frozen=True)
class PictureCheck:
    kind: str  # "photo" | "small" | "content"
    detail: str


def check_picture(image: Image, *, share: float | None = None) -> PictureCheck:
    """`share`: the part of its page or slide the picture covers, when the placement is known."""
    width, height = image.size
    if width * height < MIN_PIXELS:
        return PictureCheck("small", f"{width}×{height}px, 글자를 읽기에 너무 작음")
    aspect = width / height
    tones = tone_shares(image)
    portrait = PHOTO_ASPECT[0] <= aspect <= PHOTO_ASPECT[1]
    small = share <= PHOTO_MAX_SHARE if share is not None else width * height <= PHOTO_MAX_PIXELS
    detail = (
        f"{width}×{height}px, 가로세로 {aspect:.2f}, 바탕 {tones.background:.0%}·"
        f"글자색 {tones.ink:.1%}·중간 {tones.middle:.0%}"
        + (f", 쪽 면적의 {share:.0%}" if share is not None else "")
    )
    if portrait and small and not tones.text_like:
        return PictureCheck("photo", detail)
    return PictureCheck("content", detail)


@dataclass(frozen=True)
class Tones:
    background: float
    ink: float
    middle: float

    @property
    def text_like(self) -> bool:
        return (
            self.background >= TEXT_MIN_BACKGROUND
            and self.ink >= TEXT_MIN_INK
            and self.middle <= TEXT_MAX_MIDDLE
        )


def tone_shares(image: Image) -> Tones:
    gray = image.convert("L")
    gray.thumbnail((320, 320))
    histogram = gray.histogram()
    total = sum(histogram) or 1
    mode = max(range(256), key=lambda v: sum(histogram[max(0, v - 8) : v + 9]))
    background = sum(histogram[max(0, mode - 24) : mode + 25]) / total
    ink = sum(n for v, n in enumerate(histogram) if abs(v - mode) > 80) / total
    return Tones(background, ink, max(0.0, 1 - background - ink))
