"""Matches what the application form already says about this candidate.

This is the most reliable layer: the candidate's own name, phone, e-mail, birth date, address,
schools and employers are known exactly, so any spelling of them can be caught even when a
generic pattern would miss it ("김 도윤", "도윤", "한빛대" for 한빛대학교).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import lru_cache

from interview_assistant.deid.detectors.base import Detector
from interview_assistant.deid.detectors.contact import DATE
from interview_assistant.deid.text import HANGUL as H
from interview_assistant.deid.text import LEFT, normalize, parse_date, term_pattern
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity

_DOUBLE_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문")
_SCHOOL_ABBREVIATIONS = (
    ("여자대학교", "여대"),
    ("대학교", "대"),
    ("여자고등학교", "여고"),
    ("고등학교", "고"),
    ("여자중학교", "여중"),
    ("중학교", "중"),
)
_CORP = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사")
# Romanised surnames: in "Hyunwoo Jo" the other part is the given name, matched on its own too.
_ROMAN_SURNAMES = frozenset(
    """kim lee yi rhee park pak choi choe jung jeong chung kang cho jo yoon yun jang chang lim im
    han oh seo suh shin sin kwon hwang ahn an song ryu yoo yu hong ko koh go moon mun yang son
    bae baek paek heo huh nam shim sim noh roh ha kwak sung seong cha joo ju woo koo ku min jin
    na ji um eom chae won chun cheon bang gong hyun hyeon ham byun byeon yeom yeo""".split()
)

Rule = tuple[DeidCategory, re.Pattern[str], str]


class KnownIdentityDetector(Detector):
    name = "known_identity"
    priority = 0

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterator[Detection]:
        if known is None:
            return
        for category, pattern, value in _compile(known):
            for m in pattern.finditer(text):
                if category is DeidCategory.birthdate and parse_date(m.group()) != value:
                    continue
                yield Detection(m.start(), m.end(), category, value, self.name, self.priority)


@lru_cache(maxsize=256)
def _compile(known: KnownIdentity) -> tuple[Rule, ...]:
    rules: list[Rule] = []

    def add(category: DeidCategory, pattern: str, value: str) -> None:
        rules.append((category, re.compile(pattern), value))

    if known.name:
        for pattern in _name_patterns(known.name, known.include_given_name):
            add(DeidCategory.candidate, pattern, known.name)
        for alias in known.aliases:
            add(DeidCategory.candidate, _alias_pattern(alias), known.name)
            for given in _romanised_given_names(alias):
                add(DeidCategory.candidate, _alias_pattern(given), known.name)

    for phone in known.phones:
        add(DeidCategory.phone, _digits_pattern(phone), normalize(DeidCategory.phone, phone))

    for email in known.emails:
        value = normalize(DeidCategory.email, email)
        add(DeidCategory.email, rf"(?i:{re.escape(email.strip())})", value)

    if known.birthdate and (iso := parse_date(known.birthdate)):
        add(DeidCategory.birthdate, DATE.pattern, iso)
        add(DeidCategory.birthdate, rf"(?<!\d){iso.replace('-', '')}(?!\d)", iso)

    for address in known.addresses:
        fragments = {address, *(f.strip() for f in address.split(","))}
        for fragment in sorted(fragments, key=len, reverse=True):
            if len(fragment) >= 4:
                add(DeidCategory.address, LEFT + _flexible_spaces(fragment), address)

    for school in known.schools:
        for variant in _school_variants(school):
            add(DeidCategory.school, term_pattern(variant), school)

    for company in known.companies:
        bare = " ".join(_CORP.sub(" ", company).split())
        for variant in {company, bare}:
            add(DeidCategory.company, term_pattern(variant), company)

    return tuple(rules)


def _name_patterns(name: str, include_given: bool) -> list[str]:
    name = name.strip()
    if not re.fullmatch(rf"[{H}]{{2,5}}", name):
        return [_alias_pattern(name)]
    # Optional single space between syllables: "김도윤", "김 도윤". No right boundary, because a
    # name can carry any particle or ending ("김도윤입니다", "도윤아").
    patterns = [LEFT + r"\s?".join(name)]
    surname_len = 2 if len(name) >= 4 and name[:2] in _DOUBLE_SURNAMES else 1
    given = name[surname_len:]
    if include_given and len(given) >= 2:
        patterns.append(LEFT + given)
    return patterns


def _alias_pattern(alias: str) -> str:
    alias = alias.strip()
    if re.fullmatch(rf"[{H}]+", alias):
        return LEFT + alias
    # "Do-yoon Kim" also matches "Doyoon Kim" and "Do yoon Kim".
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias) if p]
    body = r"[\s\-]*".join(parts) if len(parts) > 1 else parts[0]
    return rf"(?<![A-Za-z0-9])(?i:{body})(?![A-Za-z0-9])"


def _romanised_given_names(alias: str) -> list[str]:
    parts = alias.split()
    if len(parts) < 2 or not alias.isascii():
        return []
    return [p for p in parts if len(p) >= 3 and p.lower().replace("-", "") not in _ROMAN_SURNAMES]


def _digits_pattern(phone: str) -> str:
    digits = normalize(DeidCategory.phone, phone)
    sep = r"[-.\s)(]{0,2}"
    local = sep.join(digits)
    alternatives = [local]
    if digits.startswith("0"):
        alternatives.append(r"\+82[-.\s]?(?:\(0\))?" + sep.join(digits[1:]))
    return rf"(?<!\d)(?:{'|'.join(alternatives)})(?!\d)"


def _flexible_spaces(fragment: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s,]+", fragment) if p]
    return r"[\s,]*".join(parts)


def _school_variants(school: str) -> list[str]:
    school = school.strip()
    variants = [school]
    for suffix, short in _SCHOOL_ABBREVIATIONS:
        if school.endswith(suffix) and len(school) > len(suffix) + 1:
            variants.append(school[: -len(suffix)] + short)
            break
    return variants
