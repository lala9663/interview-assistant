"""Last check before candidate text leaves for a model.

Prompts are built from de-identified fields only; this re-checks them anyway. Every
candidate-derived input must be free of the candidate's known identifiers (name, contact,
school, company ...) and of anything shaped like a phone number, e-mail or 주민번호. The whole
prompt must also be free of the candidate's personal identifiers, which catches candidate text
that was put into a prompt without being declared. A failing call is refused, never sent.

Only categories are reported, never values, so the exception can be logged.
"""

from __future__ import annotations

from collections.abc import Sequence

from interview_assistant.deid.detectors import KnownIdentityDetector
from interview_assistant.deid.leaks import residual_scan
from interview_assistant.deid.types import DeidCategory, KnownIdentity

# Identifiers that never belong in any prompt. Schools and companies are left out of the
# whole-prompt check because the posting itself may name a company the candidate worked for.
_PERSONAL = frozenset(
    {
        DeidCategory.candidate,
        DeidCategory.phone,
        DeidCategory.email,
        DeidCategory.birthdate,
        DeidCategory.rrn,
        DeidCategory.address,
    }
)
_KNOWN = KnownIdentityDetector()


class IdentifierInPrompt(RuntimeError):
    def __init__(self, kinds: Sequence[str]) -> None:
        super().__init__(f"prompt still holds identifiers ({', '.join(kinds)}); call refused")
        self.kinds = tuple(kinds)


def check_prompt(prompt: str, candidate_texts: Sequence[str], known: KnownIdentity | None) -> None:
    kinds: set[str] = set()
    for text in candidate_texts:
        if known is not None:
            kinds |= {d.category.value for d in _KNOWN.detect(text, known)}
        kinds |= {kind for kind, _ in residual_scan(text)}
    if known is not None:
        kinds |= {d.category.value for d in _KNOWN.detect(prompt, known) if d.category in _PERSONAL}
    if kinds:
        raise IdentifierInPrompt(sorted(kinds))
