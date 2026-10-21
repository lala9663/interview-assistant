"""Korean text helpers: word boundaries, particles, value normalisation.

Korean attaches particles (조사) to the end of a word ("카카오에서", "한빛대학교를"), so a term
match may not require a hard boundary on the right. Instead, a Hangul-final term must be
followed by a non-Hangul character or one of the endings below. This keeps "카카오에서" while
rejecting "카카오톡" or "소프트웨어".
"""

from __future__ import annotations

import re

from interview_assistant.models.deid import DeidCategory

HANGUL = "가-힣"

_ENDINGS = (
    "에서는", "에서도", "에서의", "에서", "에게", "에는", "에선", "에도", "에",
    "으로", "로", "의", "은", "는", "이", "가", "을", "를", "과", "와", "도", "만",
    "까지", "부터", "처럼", "보다", "라는", "라고", "라", "나", "며", "고", "였",
    "입니다", "이에요", "예요", "이죠", "죠", "님", "씨", "께", "분", "들", "아", "야",
    "측", "출신", "재직", "근무", "입사", "퇴사", "본사", "계열", "소속", "졸업", "재학",
)  # fmt: skip

# Left boundary: not glued to a preceding letter or digit.
LEFT = rf"(?<![{HANGUL}A-Za-z0-9])"
# Right boundary for a Hangul-final term: end, non-Hangul, or a particle / common ending.
RIGHT_HANGUL = rf"(?=$|[^{HANGUL}]|(?:{'|'.join(sorted(_ENDINGS, key=len, reverse=True))}))"
# Right boundary for a Latin/digit-final term.
RIGHT_LATIN = r"(?![A-Za-z0-9])"

_CORP_MARKERS = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사")
_DATE = re.compile(r"(\d{2,4})\s*(?:년|[.\-/])\s*(\d{1,2})\s*(?:월|[.\-/])\s*(\d{1,2})")
_COMPACT_DATE = re.compile(r"((?:19|20)\d{2})(\d{2})(\d{2})")


_PARTICLE_SUFFIX = re.compile(
    "(?:에서는|에서도|에서의|에서|에게|에는|에도|에|으로|로|의|은|는|이|가|을|를|과|와|도|까지|부터|처럼|라는)$"
)


def strip_particle(word: str) -> str:
    """'누리소프트에서' -> '누리소프트'. Keeps at least two characters."""
    m = _PARTICLE_SUFFIX.search(word)
    if m and m.start() >= 2:
        return word[: m.start()]
    return word


def right_boundary(term: str) -> str:
    return RIGHT_HANGUL if re.search(rf"[{HANGUL}]$", term) else RIGHT_LATIN


def term_pattern(term: str) -> str:
    """Regex for a literal term with boundaries.

    Spaces in the term match any run of whitespace, and a space is optional where Latin meets
    Hangul ("LG전자" also matches "LG 전자"). All-caps acronyms match case-sensitively (so
    "GIST" does not match "gist"); other Latin terms ignore case.
    """
    parts: list[str] = []
    prev = ""
    for ch in term:
        if ch.isspace():
            if parts and parts[-1] != r"\s+":
                parts.append(r"\s+")
        else:
            if prev and {_script(prev), _script(ch)} == {"hangul", "latin"}:
                parts.append(r"\s?")
            parts.append(re.escape(ch))
        prev = "" if ch.isspace() else ch
    body = "".join(parts)
    if term.isascii() and not term.isupper():
        body = f"(?i:{body})"
    return f"{LEFT}{body}{right_boundary(term)}"


def _script(ch: str) -> str:
    if "가" <= ch <= "힣":
        return "hangul"
    if ch.isascii() and ch.isalnum():
        return "latin"
    return "other"


def lookup_key(value: str) -> str:
    """Case- and whitespace-insensitive key, used to map a matched surface back to its term."""
    return re.sub(r"\s+", "", value).lower()


def parse_date(value: str) -> str | None:
    """'1995년 3월 14일', '1995.03.14', '95-3-14', '19950314' -> '1995-03-14'. None if not a date."""
    m = _DATE.search(value) or _COMPACT_DATE.fullmatch(value.strip())
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    if year < 100:
        year += 1900 if year > 30 else 2000
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def normalize(category: DeidCategory, value: str) -> str:
    """Canonical form used to decide whether two mentions are the same value."""
    collapsed = " ".join(value.split())
    if category is DeidCategory.phone:
        digits = re.sub(r"\D", "", value)
        if digits.startswith("82") and len(digits) >= 11:
            digits = "0" + digits[2:]
        return digits
    if category is DeidCategory.rrn:
        return re.sub(r"[^\d*]", "", value)
    if category is DeidCategory.email:
        return collapsed.lower()
    if category is DeidCategory.birthdate:
        return parse_date(value) or collapsed
    if category is DeidCategory.company:
        return " ".join(_CORP_MARKERS.sub(" ", value).split())
    if category is DeidCategory.candidate or category is DeidCategory.person:
        return re.sub(r"\s+", "", value) if re.fullmatch(rf"[{HANGUL}\s]+", value) else collapsed
    return collapsed
