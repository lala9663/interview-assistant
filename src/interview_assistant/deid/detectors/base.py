"""Detector interface and a rule-based implementation on top of regular expressions."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from interview_assistant.deid.text import strip_particle
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
    """

    category: DeidCategory
    pattern: re.Pattern[str]
    group: int | str = 0
    accept: Callable[[str, re.Match[str]], bool] | None = None
    strip_particle: bool = False


class RegexDetector(Detector):
    def __init__(self, name: str, priority: int, rules: Sequence[PatternRule]) -> None:
        self.name = name
        self.priority = priority
        self.rules = tuple(rules)

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterable[Detection]:
        for rule in self.rules:
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
                    yield Detection(
                        start, end, rule.category, text[start:end], self.name, self.priority
                    )
