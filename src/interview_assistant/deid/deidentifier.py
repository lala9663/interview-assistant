"""The only path from the raw zone to the LLM: raw text in, tokenised text out."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from interview_assistant.deid.detectors.base import Detector
from interview_assistant.deid.detectors.dictionary import TermDictionary
from interview_assistant.deid.store import TokenStore
from interview_assistant.deid.text import lookup_key, normalize
from interview_assistant.deid.types import (
    DeidCategory,
    DeidResult,
    Detection,
    KnownIdentity,
    Replacement,
)

_DICTIONARY_CATEGORIES = frozenset({DeidCategory.school, DeidCategory.company})
# Categories the allow list may exempt. Contact data and the candidate's own name never are.
_ALLOWABLE = frozenset(
    {DeidCategory.school, DeidCategory.company, DeidCategory.person, DeidCategory.address}
)


class Deidentifier:
    def __init__(
        self,
        detectors: Sequence[Detector],
        store: TokenStore,
        *,
        dictionary: TermDictionary | None = None,
        allow: Iterable[str] = (),
    ) -> None:
        self.detectors = tuple(detectors)
        self.store = store
        self.dictionary = dictionary
        self._allow = frozenset(lookup_key(term) for term in allow)

    def deidentify(
        self, text: str, *, candidate_id: str, known: KnownIdentity | None = None
    ) -> DeidResult:
        detections = [
            d
            for detector in self.detectors
            for d in detector.detect(text, known)
            if not self._is_allowed(d)
        ]
        out: list[str] = []
        replacements: list[Replacement] = []
        pos = 0
        for span in _merge(detections, text):
            token = self.store.token_for(candidate_id, span.category, self._canonical(span))
            out.append(text[pos : span.start])
            out.append(token)
            pos = span.end
            replacements.append(
                Replacement(span.start, span.end, span.category, token, span.detector)
            )
        out.append(text[pos:])
        return DeidResult("".join(out), tuple(replacements))

    def _canonical(self, d: Detection) -> str:
        value = normalize(d.category, d.value)
        if self.dictionary is not None and d.category in _DICTIONARY_CATEGORIES:
            value = self.dictionary.canonical(d.category, value) or value
        return value

    def _is_allowed(self, d: Detection) -> bool:
        if not self._allow or d.category not in _ALLOWABLE or d.detector == "known_identity":
            return False
        return bool({lookup_key(d.value), lookup_key(self._canonical(d))} & self._allow)


def _merge(detections: list[Detection], text: str) -> list[Detection]:
    """Union overlapping spans so no detected character survives.

    Each cluster is labelled by its longest detection (ties: lower priority number). If the union
    is wider than that detection, the union's surface becomes the value.
    """
    clusters: list[list[Detection]] = []
    for d in sorted(detections, key=lambda d: (d.start, -d.end)):
        if clusters and d.start < max(c.end for c in clusters[-1]):
            clusters[-1].append(d)
        else:
            clusters.append([d])

    merged: list[Detection] = []
    for cluster in clusters:
        start = min(d.start for d in cluster)
        end = max(d.end for d in cluster)
        best = min(cluster, key=lambda d: (-d.length, d.priority))
        value = best.value if (best.start, best.end) == (start, end) else text[start:end]
        merged.append(Detection(start, end, best.category, value, best.detector, best.priority))
    return merged
