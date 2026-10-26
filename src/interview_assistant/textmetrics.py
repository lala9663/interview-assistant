"""Character error rate, shared by the STT connection test and the OCR quality measurements."""

from __future__ import annotations

import unicodedata


def normalize(text: str) -> str:
    """For error rates: NFC, no spaces or punctuation, lower case."""
    text = unicodedata.normalize("NFC", text).lower()
    return "".join(c for c in text if not (c.isspace() or unicodedata.category(c).startswith("P")))


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate: edit distance over the reference length, both normalized."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / len(ref)
