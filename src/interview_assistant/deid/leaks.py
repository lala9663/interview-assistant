"""Leak check: does any known identifying value survive de-identification?

A sample is a text plus its ground truth: every identifying value that appears in it. After
de-identification none of them may remain, in any spacing or separator variant. A residual scan
also flags anything still shaped like a phone number, e-mail or 주민번호 even if it is not in
the ground truth. Optional `keep` phrases guard the other direction: words that are not
identifying must survive, so over-eager patterns do not garble what the LLM reads.
Used by scripts/check_leaks.py and the test suite.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy.pool import StaticPool

from interview_assistant.crypto import FieldCipher
from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.deid.config import DeidConfig, build_deidentifier
from interview_assistant.deid.detectors.contact import EMAIL, PHONE, RRN
from interview_assistant.deid.identity import open_identity, seal_identity
from interview_assistant.deid.store import SqlTokenStore
from interview_assistant.deid.text import parse_date
from interview_assistant.deid.types import DeidCategory, KnownIdentity
from interview_assistant.models import Base, Candidate


@dataclass(frozen=True)
class ExpectedValue:
    category: DeidCategory
    value: str


@dataclass(frozen=True)
class Sample:
    id: str
    kind: str
    text: str
    identity: KnownIdentity
    expected: tuple[ExpectedValue, ...]
    keep: tuple[str, ...] = ()


@dataclass
class SampleReport:
    sample_id: str
    kind: str
    output: str
    expected: int
    replaced: int
    leaks: list[ExpectedValue] = field(default_factory=list)
    residual: list[tuple[str, str]] = field(default_factory=list)  # (kind, surface)
    lost: list[str] = field(default_factory=list)  # `keep` phrases that were replaced
    not_in_source: list[str] = field(default_factory=list)  # fixture errors

    @property
    def ok(self) -> bool:
        return not (self.leaks or self.residual or self.lost or self.not_in_source)


def load_samples(path: Path) -> list[Sample]:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    samples = []
    for item in raw.get("samples", []):
        samples.append(
            Sample(
                id=str(item["id"]),
                kind=str(item.get("kind", "")),
                text=str(item["text"]),
                identity=KnownIdentity.from_dict(item.get("identity") or {}),
                expected=tuple(
                    ExpectedValue(DeidCategory(e["category"]), str(e["value"]))
                    for e in item.get("expected", [])
                ),
                keep=tuple(str(k) for k in item.get("keep", [])),
            )
        )
    return samples


def leak_pattern(expected: ExpectedValue) -> re.Pattern[str]:
    """Pattern for a value in any spacing / separator / case variant."""
    category, value = expected.category, expected.value
    if category in (DeidCategory.phone, DeidCategory.rrn):
        digits = re.sub(r"[^\d*]", "", value)
        variants = {digits}
        if category is DeidCategory.phone and digits.startswith("82"):
            variants.add("0" + digits[2:])
        if category is DeidCategory.phone and digits.startswith("0"):
            variants.add("82" + digits[1:])
        sep = r"[\s.\-()+]{0,3}"
        return re.compile("|".join(sep.join(re.escape(c) for c in v) for v in variants))
    if category is DeidCategory.birthdate:
        iso = parse_date(value)
        if iso:
            y, m, d = iso.split("-")
            sep = r"\s*(?:[.\-/]|년|월)?\s*"
            return re.compile(
                rf"(?:{y}|{y[2:]}){sep}0?{int(m)}{sep}0?{int(d)}(?!\d)|{y}{m}{d}"
            )
    chars = [re.escape(c) for c in value if not c.isspace()]
    return re.compile(r"\s*".join(chars), re.IGNORECASE)


def find_leaks(output: str, expected: Sequence[ExpectedValue]) -> list[ExpectedValue]:
    leaks = [e for e in expected if leak_pattern(e).search(output)]
    # The local part of an e-mail address identifies a person on its own.
    for e in expected:
        if e.category is DeidCategory.email and e not in leaks:
            local = e.value.split("@", 1)[0]
            if len(local) >= 4 and local.lower() in output.lower():
                leaks.append(e)
    return leaks


def residual_scan(output: str) -> list[tuple[str, str]]:
    found = []
    for kind, pattern in (("rrn", RRN), ("phone", PHONE), ("email", EMAIL)):
        found.extend((kind, m.group()) for m in pattern.finditer(output))
    return found


def check_sample(sample: Sample, deidentify: Callable[[Sample], tuple[str, int]]) -> SampleReport:
    output, replaced = deidentify(sample)
    return SampleReport(
        sample_id=sample.id,
        kind=sample.kind,
        output=output,
        expected=len(sample.expected),
        replaced=replaced,
        leaks=find_leaks(output, sample.expected),
        residual=residual_scan(output),
        lost=[k for k in sample.keep if k not in output],
        not_in_source=[
            *(e.value for e in sample.expected if not leak_pattern(e).search(sample.text)),
            *(k for k in sample.keep if k not in sample.text),
        ],
    )


def run_leak_check(samples: Sequence[Sample], config: DeidConfig) -> list[SampleReport]:
    """De-identify every sample through the real path and check it.

    Real path: in-memory SQLite, identity sealed into Candidate.encrypted_identity and opened
    again, tokens persisted (encrypted) in deid_mappings. The key is throwaway. No network.
    """
    engine = make_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = FieldCipher(FieldCipher.generate_key())
    try:
        with make_session_factory(engine)() as session:
            deid = build_deidentifier(
                config, SqlTokenStore(session, cipher, config.token_formats())
            )

            def deidentify(sample: Sample) -> tuple[str, int]:
                candidate = Candidate(
                    pseudonym=f"LEAKCHECK-{sample.id}",
                    encrypted_identity=seal_identity(cipher, sample.identity),
                )
                session.add(candidate)
                session.flush()
                known = open_identity(cipher, candidate.encrypted_identity or "")
                result = deid.deidentify(sample.text, candidate_id=candidate.id, known=known)
                return result.text, len(result.replacements)

            reports = [check_sample(s, deidentify) for s in samples]
            session.rollback()
    finally:
        engine.dispose()
    return reports


def mask(value: str) -> str:
    """'김도윤' -> '김**', '010-0123-4567' -> '01***********'. For reports on real data."""
    visible = 2 if len(value) > 6 else 1
    return value[:visible] + "*" * (len(value) - visible)
