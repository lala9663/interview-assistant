"""Adapter for a Korean NER model. No model ships with the PoC; this is the plug point.

To add one, implement `EntityRecognizer.recognize` (e.g. a KLUE-NER checkpoint running on an
in-house host, never an external API) and pass it to `build_deidentifier(..., recognizer=...)`
with "ner" in the `detectors` list of config/deid.yaml.

Only person names are mapped by default. Organisation and location labels are opt-in through
`labels`, because a model's ORG/LOC spans overlap heavily with what the dictionary already
handles and would otherwise turn every "서울" into an address token.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from interview_assistant.deid.detectors.base import Detector
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity

DEFAULT_LABELS: Mapping[str, DeidCategory] = {
    "PS": DeidCategory.person,  # KLUE
    "PER": DeidCategory.person,
    "PERSON": DeidCategory.person,
}


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    label: str


class EntityRecognizer(Protocol):
    def recognize(self, text: str) -> Sequence[Entity]: ...


class NERDetector(Detector):
    name = "ner"
    priority = 5

    def __init__(
        self, recognizer: EntityRecognizer, labels: Mapping[str, DeidCategory] | None = None
    ) -> None:
        self.recognizer = recognizer
        self.labels = dict(DEFAULT_LABELS if labels is None else labels)

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterator[Detection]:
        for entity in self.recognizer.recognize(text):
            category = self.labels.get(entity.label)
            if category is not None and 0 <= entity.start < entity.end <= len(text):
                yield Detection(
                    entity.start,
                    entity.end,
                    category,
                    text[entity.start : entity.end],
                    self.name,
                    self.priority,
                )
