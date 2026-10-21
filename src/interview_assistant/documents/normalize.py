"""Clean-up applied to every piece of text an extractor returns.

Files carry characters that split a value for a pattern but not for a reader or an LLM:
zero-width spaces inside a name, decomposed Hangul from macOS file names (NFD), full-width
digits in a phone number, non-breaking spaces between letters. Normalising here, before
de-identification, keeps the detectors' patterns simple and closes those gaps for every format.
"""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = dict.fromkeys(
    map(ord, "­͏᠎​‌‍‎‏⁠⁡⁢⁣⁤﻿"),
    None,
)
_FULLWIDTH = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)}
_LINE_BREAKS = dict.fromkeys(map(ord, "\v\f\x85  "), "\n")
_SPACES = re.compile(r"[^\S\n]+")  # any whitespace except newline: tab, NBSP, ideographic space
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_LINE_BREAKS)
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE).translate(_FULLWIDTH)
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def collapse(text: str) -> str:
    """One line: every run of whitespace, newlines included, becomes one space (table cells)."""
    return " ".join(normalize_text(text).split())
