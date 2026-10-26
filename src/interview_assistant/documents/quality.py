"""Is a text layer garbled? Characters a correct text layer of a Korean resume would not produce.

A PDF whose font maps its glyphs to the wrong code points (legacy Hangul fonts, broken ToUnicode
maps) shows Korean on screen but reads as "ÀÌ·Â¼­ ±ÇÇÏ¸°": EUC-KR bytes taken for Latin-1. Such
text must not reach the LLM. It reads as nonsense to the de-identifier, so a name in it is never
replaced, yet the bytes can be decoded back into the name. A garbled page is read again by OCR
or, where nothing can render it, held.

Suspicious characters (each counts once):
- unmapped glyphs (pdfminer's "(cid:123)"), U+FFFD, control, private-use and unassigned code points
- Latin-1 Supplement and Latin Extended letters and signs (U+0080..U+024F), the mojibake of
  EUC-KR/CP949 read as Latin-1; a few signs real resumes use (· × ° ± © ® ² ³ ...) only when two
  or more such characters stand together
- conjoining Hangul jamo and half-width Hangul, which normalised text no longer contains
- letters of scripts a Korean resume does not use (Cyrillic, Arabic, Hebrew, Thai, ...)

A text is garbled when the share of suspicious characters reaches the sensitivity's ratio, or when
it holds a run of consecutive suspicious characters that long (a single broken font, e.g. only the
name in a decorative font). An accented letter in "José" is a run of one and passes.

Not caught: a font mapped onto other, valid Hangul syllables (wrong but well-formed text), and
ASCII-only gibberish. Those need a language model and stay a known gap (docs/document-reading.md).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# sensitivity -> (share of suspicious characters, run length); None: no run rule
SENSITIVITY: dict[str, tuple[float, int | None]] = {
    "low": (0.30, None),
    "medium": (0.15, 3),
    "high": (0.05, 2),
}
MIN_CHARS = 20  # the share rule needs this many characters to mean anything

_CID = re.compile(r"\(cid:\d+\)")
_UNMAPPED = "�"
_ALLOWED_LATIN1 = frozenset("·×÷°±²³¹¼½¾§¶©®µ¢£¥€«»¿¡ªº¦¬¯´¨¸ ­")
_OK_LETTER_RANGES = (
    (0x0041, 0x005A),
    (0x0061, 0x007A),
    (0x0370, 0x03FF),  # Greek (α, β in technical resumes)
    (0x3040, 0x30FF),  # Kana
    (0x3130, 0x318F),  # Hangul compatibility jamo ("ㅇ" bullets)
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),  # Hanja
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0xF900, 0xFAFF),
)


@dataclass(frozen=True)
class TextQuality:
    chars: int  # non-space characters looked at
    suspicious: int
    longest_run: int  # longest run of consecutive suspicious characters (spaces end a run)

    @property
    def ratio(self) -> float:
        return self.suspicious / self.chars if self.chars else 0.0

    def garbled(self, sensitivity: str = "medium") -> bool:
        share, run = SENSITIVITY[sensitivity]
        if run is not None and self.longest_run >= run:
            return True
        return self.chars >= MIN_CHARS and self.ratio >= share

    def describe(self) -> str:
        return f"의심 글자 {self.suspicious}/{self.chars}자 ({self.ratio:.0%}), 최장 연속 {self.longest_run}자"


def assess(text: str) -> TextQuality:
    text = _CID.sub(_UNMAPPED, text)
    flags = [_suspicious(c) for c in text]
    # Latin-1 signs real text uses ("학력·경력", "±0.5") are fine alone, but two or more Latin
    # characters in a row are mojibake: "가" in CP949 read as Latin-1 is "°¡", both such signs.
    i = 0
    while i < len(text):
        if not _latin(text[i]):
            i += 1
            continue
        j = i
        while j < len(text) and _latin(text[j]):
            j += 1
        if j - i >= 2:
            flags[i:j] = [True] * (j - i)
        i = j
    chars = suspicious = run = longest = 0
    for c, flag in zip(text, flags, strict=True):
        if c.isspace():
            run = 0
            continue
        chars += 1
        if flag:
            suspicious += 1
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return TextQuality(chars, suspicious, longest)


def _latin(c: str) -> bool:
    return 0x0080 <= ord(c) <= 0x024F and not c.isspace()


def _suspicious(c: str) -> bool:
    """On its own, without looking at the neighbours."""
    cp = ord(c)
    if c == _UNMAPPED:
        return True
    category = unicodedata.category(c)
    if category in ("Cc", "Co", "Cn", "Cs") and not c.isspace():
        return True
    if 0x0080 <= cp <= 0x024F:
        return c not in _ALLOWED_LATIN1
    if 0x1100 <= cp <= 0x11FF or 0xFFA0 <= cp <= 0xFFDC:
        return True
    if category.startswith("L") and cp > 0x7F:
        return not any(lo <= cp <= hi for lo, hi in _OK_LETTER_RANGES)
    return False
