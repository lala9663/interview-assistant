"""Detector interface and a rule-based implementation on top of regular expressions."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from interview_assistant.deid.text import Spaceless, strip_particle, without_letter_spacing
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity


class Detector(ABC):
    """Finds identifying spans in text. Implementations must not call out over the network.

    `priority` breaks ties when two detectors claim exactly the same span (lower wins); otherwise
    the longest span wins. Known identity is most trusted, heuristics least.
    """

    name: str
    priority: int

    @abstractmethod
    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterable[Detection]: ...


@dataclass(frozen=True)
class PatternRule:
    """One regex. `group` selects the span to replace; `accept` can veto a match by context.

    `strip_particle` drops a trailing 조사 from the span, for patterns that end in an open-ended
    name ("(주)누리소프트에서" -> "(주)누리소프트").

    `spaced` also runs the pattern on a copy of the text without letter spacing
    (`without_letter_spacing`), for values whose shape survives losing word boundaries: a phone
    number keeps its prefix and digit count, an e-mail its @ and domain. Only matches that span
    removed spaces are taken from the copy; the rest is what the original text already shows.
    Leave it off for patterns that need word boundaries in the original (names).
    """

    category: DeidCategory
    pattern: re.Pattern[str]
    group: int | str = 0
    accept: Callable[[str, re.Match[str]], bool] | None = None
    strip_particle: bool = False
    spaced: bool = False


class RegexDetector(Detector):
    def __init__(self, name: str, priority: int, rules: Sequence[PatternRule]) -> None:
        self.name = name
        self.priority = priority
        self.rules = tuple(rules)

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterable[Detection]:
        spaceless: Spaceless | None = None
        for rule in self.rules:
            for start, end in _spans(rule, text):
                yield Detection(
                    start, end, rule.category, text[start:end], self.name, self.priority
                )
            if not rule.spaced:
                continue
            spaceless = spaceless or without_letter_spacing(text)
            for start, end in _spans(rule, spaceless.text):
                if spaceless.dropped_inside(start, end):
                    # The value is the de-spaced surface, so "누 리 대 학 교" and "누리대학교"
                    # get the same token.
                    value = spaceless.text[start:end]
                    start, end = spaceless.source_span(start, end)
                    yield Detection(start, end, rule.category, value, self.name, self.priority)


def _spans(rule: PatternRule, text: str) -> Iterator[tuple[int, int]]:
    for m in rule.pattern.finditer(text):
        if rule.accept is not None and not rule.accept(text, m):
            continue
        start, end = m.span(rule.group)
        surface = text[start:end]
        if rule.strip_particle:
            end = start + len(strip_particle(surface))
            surface = text[start:end]
        # Trim whitespace a greedy pattern may have swallowed at the edges.
        start += len(surface) - len(surface.lstrip())
        end -= len(surface) - len(surface.rstrip())
        if end > start:
            yield start, end
