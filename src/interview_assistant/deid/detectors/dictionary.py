"""Dictionary of school and company names, and the detector that matches them.

Dictionary files are plain text, one entry per line:

    서울대학교 | 서울대 | SNU | Seoul National University

The first name is canonical; every alias maps to it, so "서울대" and "SNU" get the same token.
Blank lines and lines starting with # are ignored. Several files per category are merged, so an
in-house list can sit next to the public draft.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

from interview_assistant.deid.detectors.base import Detector
from interview_assistant.deid.text import lookup_key, term_pattern
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity


class TermDictionary:
    def __init__(
        self, entries: Mapping[DeidCategory, Iterable[Sequence[str]]] | None = None
    ) -> None:
        self._canonical: dict[DeidCategory, dict[str, str]] = {}
        self._surfaces: dict[DeidCategory, list[str]] = {}
        for category, rows in (entries or {}).items():
            for row in rows:
                self.add(category, row[0], row[1:])

    @classmethod
    def load(cls, files: Mapping[DeidCategory, Sequence[Path]]) -> TermDictionary:
        dictionary = cls()
        for category, paths in files.items():
            for path in paths:
                for lineno, names in parse_lines(Path(path).read_text(encoding="utf-8")):
                    try:
                        dictionary.add(category, names[0], names[1:])
                    except ValueError as exc:
                        raise ValueError(f"{path}:{lineno}: {exc}") from None
        return dictionary

    def add(self, category: DeidCategory, canonical: str, aliases: Iterable[str] = ()) -> None:
        keys = self._canonical.setdefault(category, {})
        surfaces = self._surfaces.setdefault(category, [])
        for surface in (canonical, *aliases):
            key = lookup_key(surface)
            existing = keys.get(key)
            if existing is not None and existing != canonical:
                raise ValueError(f"'{surface}' already maps to '{existing}'")
            if existing is None:
                keys[key] = canonical
                surfaces.append(surface)

    def canonical(self, category: DeidCategory, surface: str) -> str | None:
        return self._canonical.get(category, {}).get(lookup_key(surface))

    def surfaces(self, category: DeidCategory) -> list[str]:
        return list(self._surfaces.get(category, ()))

    def categories(self) -> list[DeidCategory]:
        return [c for c, s in self._surfaces.items() if s]

    def __len__(self) -> int:
        return sum(len(v) for v in self._canonical.values())


def parse_lines(content: str) -> Iterator[tuple[int, list[str]]]:
    for lineno, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names = [part.strip() for part in line.split("|") if part.strip()]
        if names:
            yield lineno, names


class DictionaryDetector(Detector):
    name = "dictionary"
    priority = 2

    def __init__(self, dictionary: TermDictionary) -> None:
        self.dictionary = dictionary
        self._patterns: dict[DeidCategory, re.Pattern[str]] = {}
        for category in dictionary.categories():
            surfaces = sorted(dictionary.surfaces(category), key=len, reverse=True)
            self._patterns[category] = re.compile("|".join(term_pattern(s) for s in surfaces))

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterator[Detection]:
        for category, pattern in self._patterns.items():
            for m in pattern.finditer(text):
                canonical = self.dictionary.canonical(category, m.group()) or m.group()
                yield Detection(m.start(), m.end(), category, canonical, self.name, self.priority)
