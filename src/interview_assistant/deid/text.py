"""Korean text helpers: word boundaries, particles, value normalisation, spaceless copies.

Korean attaches particles (조사) to the end of a word ("카카오에서", "한빛대학교를"), so a term
match may not require a hard boundary on the right. Instead, a Hangul-final term must be
followed by a non-Hangul character or one of the endings below. This keeps "카카오에서" while
rejecting "카카오톡" or "소프트웨어".

Letter-spaced writing ("0 1 0 - 1 2 3 4 - 5 6 7 8", "누 리 대 학 교") defeats patterns that
expect a value written together. `without_letter_spacing` makes a copy with those spaces
removed and a map back to the original positions, so a pattern can run on the copy and still
replace the spaced surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

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


def term_pattern(term: str, *, loose: bool = False) -> str:
    """Regex for a literal term with boundaries.

    Spaces in the term match any run of whitespace, and a space is optional where Latin meets
    Hangul ("LG전자" also matches "LG 전자"). All-caps acronyms match case-sensitively (so
    "GIST" does not match "gist"); other Latin terms ignore case.

    `loose` also allows one whitespace character between any two letters, for values known
    exactly (the candidate's own school or employer) that a document may have wrapped mid-word
    in a narrow table cell ("한빛대" / "학교").
    """
    parts: list[str] = []
    prev = ""
    for ch in term:
        if ch.isspace():
            if parts and parts[-1] != r"\s+":
                parts.append(r"\s+")
        else:
            if prev and (loose or {_script(prev), _script(ch)} == {"hangul", "latin"}):
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


@dataclass(frozen=True)
class Spaceless:
    """A copy of a text with spaces removed, and where each remaining character came from.

    Patterns run on `text`; `source_span` maps a match back to the original text, so the
    replacement covers the letter-spaced surface ("0 1 0 - 1 2 3 4 - 5 6 7 8"). Line breaks
    are kept.
    """

    text: str
    origin: tuple[int, ...]  # origin[i] is the index in the original text of text[i]

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        return self.origin[start], self.origin[end - 1] + 1

    def dropped_inside(self, start: int, end: int) -> bool:
        """True when the copy removed whitespace inside this span, i.e. the match is not
        something the original text already shows as is."""
        return end - start >= 2 and self.origin[end - 1] - self.origin[start] != end - 1 - start


_HSPACE = re.compile(r"[^\S\n]+")
_TOKEN = re.compile(r"[^\s]+")
_CONNECTORS = frozenset("@.-_")


def without_spaces(text: str) -> Spaceless:
    """Every space and tab removed. Words run together; for scans that only look for
    structured shapes (phone, e-mail, 주민번호), such as the leak checker's residual scan."""
    return _drop(text, [m.span() for m in _HSPACE.finditer(text)])


def without_letter_spacing(text: str) -> Spaceless:
    """Only the spaces of letter-spaced writing removed: "누 리 대 학 교" -> "누리대학교",
    "j o h n @ e x a m p l e . c o m" and "john @ example . com" -> "john@example.com".

    A space goes when both neighbours are single characters, or when one neighbour is a
    connector (@ . - _) on its own or starts/ends with @. Spaces between ordinary words stay,
    so "있는 대학교" never reads as one school name. Within a run of single characters only the
    narrowest spacing goes; wider gaps ("권 하 린   이 력 서") are kept as word breaks.
    """
    gaps: list[tuple[int, int]] = []
    for line in re.finditer(r"[^\n]+", text):
        tokens = [m.span() for m in _TOKEN.finditer(text, line.start(), line.end())]
        words = [text[s:e] for s, e in tokens]
        between = [(tokens[i][1], tokens[i + 1][0]) for i in range(len(tokens) - 1)]
        for i, (a, b) in enumerate(pairwise(words)):
            if _is_connector(a) or _is_connector(b) or a.endswith("@") or b.startswith("@"):
                gaps.append(between[i])
        i = 0
        while i < len(words):
            j = i
            while j + 1 < len(words) and len(words[j]) == 1 and len(words[j + 1]) == 1:
                j += 1
            if j > i:
                narrowest = min(e - s for s, e in between[i:j])
                gaps.extend(g for g in between[i:j] if g[1] - g[0] == narrowest)
            i = j + 1
    return _drop(text, gaps)


def _is_connector(word: str) -> bool:
    return all(ch in _CONNECTORS for ch in word)


def _drop(text: str, gaps: list[tuple[int, int]]) -> Spaceless:
    removed = bytearray(len(text))
    for start, end in gaps:
        removed[start:end] = b"\x01" * (end - start)
    origin = tuple(i for i in range(len(text)) if not removed[i])
    return Spaceless("".join(text[i] for i in origin), origin)


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
        return re.sub(r"\s+", "", value).lower()  # an address never contains spaces
    if category is DeidCategory.birthdate:
        return parse_date(value) or collapsed
    if category is DeidCategory.company:
        return " ".join(_CORP_MARKERS.sub(" ", value).split())
    if category is DeidCategory.candidate or category is DeidCategory.person:
        return re.sub(r"\s+", "", value) if re.fullmatch(rf"[{HANGUL}\s]+", value) else collapsed
    return collapsed
