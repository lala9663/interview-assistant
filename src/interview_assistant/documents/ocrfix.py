"""Corrections applied to every OCR line before anything else sees it.

OCR engines confuse digits with look-alike letters ("010-138l-O274", "1991.l2.12"). A phone number
read that way slips past the de-identifier's patterns, so inside runs that are mostly digits the
look-alikes become digits again. Runs that are mostly letters ("Geum", "B2B") are left alone.
A copyright or registered sign between letters is an at sign read wrong ("geum©example.org").
"""

from __future__ import annotations

import re

_LOOKALIKE = str.maketrans(
    {"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "!": "1", "i": "1",
     "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "b": "6", "G": "6", "g": "9", "q": "9"}
)  # fmt: skip
_RUN = re.compile(r"[0-9OoDQIl|!iZzSsBbGgq]+(?:[-.\s()/:~]{1,2}[0-9OoDQIl|!iZzSsBbGgq]+)*")
_AT = re.compile(r"(?<=[A-Za-z0-9._%+-])\s?[©®]\s?(?=[A-Za-z0-9-]+\.[A-Za-z])")


def correct(text: str) -> str:
    text = _AT.sub("@", text)
    return _RUN.sub(_digits, text)


def _digits(m: re.Match[str]) -> str:
    run = m.group()
    alnum = [c for c in run if c.isalnum()]
    digits = sum(c.isdigit() for c in alnum)
    if digits < 4 or digits < 0.6 * len(alnum):
        return run
    return run.translate(_LOOKALIKE)
