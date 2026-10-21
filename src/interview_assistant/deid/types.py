"""Value types shared by detectors, the de-identifier and the leak checker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from interview_assistant.models.deid import DeidCategory

__all__ = ["DeidCategory", "DeidResult", "Detection", "KnownIdentity", "Replacement"]


@dataclass(frozen=True)
class Detection:
    """A span of the input to replace. `value` is the raw surface or a canonical form."""

    start: int
    end: int
    category: DeidCategory
    value: str
    detector: str
    priority: int  # lower wins when two detections cover the same span

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class Replacement:
    """Where a token went. Carries no original value, so results can be logged safely."""

    start: int
    end: int
    category: DeidCategory
    token: str
    detector: str


@dataclass(frozen=True)
class DeidResult:
    text: str
    replacements: tuple[Replacement, ...]


@dataclass(frozen=True)
class KnownIdentity:
    """What the application form already tells us about the candidate (raw zone only).

    `aliases` holds other spellings of the candidate's name (English name, nickname).
    `birthdate` accepts any common format; it is compared after normalisation.
    """

    name: str | None = None
    aliases: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    birthdate: str | None = None
    addresses: tuple[str, ...] = ()
    schools: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    include_given_name: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnownIdentity:
        def tup(key: str) -> tuple[str, ...]:
            raw = data.get(key) or ()
            return (raw,) if isinstance(raw, str) else tuple(str(v) for v in raw)

        birthdate = data.get("birthdate")
        return cls(
            name=data.get("name"),
            aliases=tup("aliases"),
            phones=tup("phones"),
            emails=tup("emails"),
            birthdate=str(birthdate) if birthdate is not None else None,
            addresses=tup("addresses"),
            schools=tup("schools"),
            companies=tup("companies"),
            include_given_name=bool(data.get("include_given_name", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: list(v) if isinstance(v, tuple) else v for k, v in data.items()}
