"""Regex detector for contact data: phone, e-mail, 주민등록번호, date of birth, street address."""

from __future__ import annotations

import re

from interview_assistant.deid.detectors.base import PatternRule, RegexDetector
from interview_assistant.deid.text import HANGUL as H
from interview_assistant.deid.text import LEFT, RIGHT_HANGUL
from interview_assistant.deid.types import DeidCategory

PHONE = re.compile(
    r"(?<![\d+])(?:\+82[-.\s]?(?:\(0\))?|0)(?:1[016789]|2|[3-6][1-5]|70)"
    r"[-.\s)]{0,2}\d{3,4}[-.\s]{0,2}\d{4}(?!\d)"
)
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    r"(?![A-Za-z])"
)
RRN = re.compile(
    r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s*-?\s*[1-8*][\d*]{6}(?![\d*])"
)
DATE = re.compile(
    r"(?<!\d)(?:(?:19|20)\d{2}|\d{2})\s*(?:년\s*|[.\-/]\s*)(?:0?[1-9]|1[0-2])\s*(?:월\s*|[.\-/]\s*)"
    r"(?:0?[1-9]|[12]\d|3[01])(?:\s*일)?(?!\d)"
)

# A date is only a birth date when the context says so; other dates (입사일 등) stay.
_BIRTH_BEFORE = re.compile(r"생년월일|출생|생일|태어난|D\.?O\.?B|[Bb]irth|[Bb]orn")
_BIRTH_AFTER = re.compile(r"^\s*(?:생(?![산활각명존])|출생|태생|에\s*(?:태어|출생))")


def _is_birthdate(text: str, m: re.Match[str]) -> bool:
    before = text[max(0, m.start() - 20) : m.start()]
    after = text[m.end() : m.end() + 10]
    return bool(_BIRTH_BEFORE.search(before) or _BIRTH_AFTER.match(after))


_SIDO = sorted(
    """서울특별시 서울시 서울 부산광역시 부산시 부산 대구광역시 대구시 대구 인천광역시 인천시 인천
    광주광역시 광주시 광주 대전광역시 대전시 대전 울산광역시 울산시 울산 세종특별자치시 세종시 세종
    경기도 경기 강원특별자치도 강원도 강원 충청북도 충북 충청남도 충남 전북특별자치도 전라북도 전북
    전라남도 전남 경상북도 경북 경상남도 경남 제주특별자치도 제주도 제주""".split(),
    key=len,
    reverse=True,
)
# Common words that end in 시/군/구 but are not districts.
_NOT_DISTRICT = (
    "연구 친구 도구 요구 탐구 추구 가구 입구 출구 지구 기구 용구 공구 문구 학구 "
    "당시 동시 역시 혹시 다시 감시 무시 제시 표시 지시 게시 명시 중시 일시 임시 즉시 수시 상시 "
    "도시 전시 실시 장군 해군 공군 육군 대군 증후군"
).split()

_DISTRICT = rf"(?!(?:{'|'.join(_NOT_DISTRICT)}){RIGHT_HANGUL})[{H}]{{1,5}}(?:시|군|구){RIGHT_HANGUL}"
_NUMBER = r"\d{1,5}(?:-\d{1,5})?"
_ROAD = rf"[{H}0-9]{{1,12}}(?:로|길)\s*{_NUMBER}(?:번길\s*{_NUMBER})?"
_DONG = rf"[{H}]{{1,10}}(?:\d{{1,2}}가|동|읍|면|리)(?:\s*{_NUMBER}(?:번지)?)?{RIGHT_HANGUL}"
_UNIT = r"\d{1,4}\s*동\s*\d{1,5}\s*호|\d{1,5}\s*호|\d{1,3}\s*층"
_BUILDING = rf"[{H}A-Za-z0-9]{{1,15}}(?:아파트|빌라|오피스텔|맨션|빌딩|타워|하이츠)"
_TAIL = (
    rf"(?:\s*,?\s*{_BUILDING})?(?:\s*,?\s*(?:{_UNIT}))*(?:\s*\([{H}0-9,\s]{{1,20}}\))?"
)
_PART = rf"(?:{_DISTRICT}|{_ROAD}|{_DONG})"

# Pieces of a known address that identify on their own (road + number, building, unit). The
# known-identity detector looks for them separately, because a document can split an address
# across table cells ("서울특별시 마포구 | 솔바람길 27").
ADDRESS_PIECE = re.compile(rf"{_ROAD}|{_BUILDING}|\d{{1,4}}\s*동\s*\d{{1,5}}\s*호")
# The 시/도 + 시/군/구 head of an address ("경기도 수원시 영통구"), also looked for on its own so a
# split address gets one token rather than one per cell.
ADDRESS_REGION = re.compile(rf"^(?:{'|'.join(_SIDO)})(?:\s*{_DISTRICT})*")

# 시/도 + 시/군/구 (+ 도로명/동 + 번지 + 건물·호수). "서울 강남구" alone already counts.
ADDRESS_WITH_SIDO = re.compile(
    rf"{LEFT}(?:{'|'.join(_SIDO)})\s*{_DISTRICT}(?:\s*{_PART})*{_TAIL}"
)
# No 시/도: a district followed by at least one more address part ("분당구 정자일로 95").
ADDRESS_NO_SIDO = re.compile(rf"{LEFT}{_DISTRICT}(?:\s*{_PART})+{_TAIL}")


def contact_detector() -> RegexDetector:
    return RegexDetector(
        "regex",
        priority=1,
        rules=[
            PatternRule(DeidCategory.rrn, RRN),
            PatternRule(DeidCategory.phone, PHONE),
            PatternRule(DeidCategory.email, EMAIL),
            PatternRule(DeidCategory.birthdate, DATE, accept=_is_birthdate),
            PatternRule(DeidCategory.address, ADDRESS_WITH_SIDO),
            PatternRule(DeidCategory.address, ADDRESS_NO_SIDO),
        ],
    )
